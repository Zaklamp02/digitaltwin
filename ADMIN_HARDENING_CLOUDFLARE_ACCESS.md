# Admin Hardening with Cloudflare Access

**Objective:** Restrict access to admin endpoints (`/admin/*` and `/api/admin/*`) to only authenticated owners using Cloudflare Zero Trust.

**Architecture:**
- Cloudflare Access provides edge-level authentication (no app code change required)
- Optional: Backend validates CF JWT token for additional security
- Public paths (chat, knowledge, suggestions) remain open and unauthenticated

---

## 1. Cloudflare Access Setup (One-time)

### 1.1. Prerequisites

- Cloudflare account with the domain (e.g., `sebastiaandenboer.org`)
- Admin access to CF dashboard
- Cloudflare plan that includes Access (free tier available with team invites)

### 1.2. Create CF Access application for admin paths

In Cloudflare Zero Trust dashboard:

1. **Go to:** Access > Applications > Create
2. **Application name:** `digital-twin-admin`
3. **Subdomain:** `sebastiaandenboer.org` (or your domain)
4. **Path:** `/admin`
5. **Application type:** `Self-hosted`

### 1.3. Configure authentication policy

**Policy name:** `admin-owner-only`

**Rule logic:**
```
IF Email domain == sebastiaandenboer.org
OR Email == your-email@your-provider.com
THEN Allow
```

**Authentication methods** (choose one or both):

**Option A: Email OTP (free, no setup)**
- Send one-time passcode to email
- Less friction, still secure

**Option B: Google/GitHub SSO**
- Sign in with social account
- More seamless for owners

**Option C: SAML (enterprise)**
- Requires SSO provider setup

**Recommended:** Email OTP for simplicity, or Google SSO if you have Google account.

### 1.4. Add policy rules

```
Rule Name: Owner Email
Action: Allow
Conditions: 
  - Email is: <YOUR_EMAIL@DOMAIN.COM>

Rule Name: Deny All Others
Action: Deny
```

### 1.5. Configure CF Access token

1. **Go to:** Access > Applications > Your app > Edit
2. **Enable:** "Require authentication to access this application"
3. **JWT expiration:** 24 hours (default)
4. **Auto-redirect:** Enable (auto-login if already authenticated)

### 1.6. Configure multiple paths

Repeat for `/api/admin/*`:

```yaml
Application: digital-twin-admin-api
Path: /api/admin
Policy: admin-owner-only
```

---

## 2. Access Flow

```
User visits https://sebastiaandenboer.org/admin
          ↓
    Cloudflare Edge
          ↓
   Is user authenticated?
    /          \
  YES           NO
   ↓            ↓
Allow       Show login page
 ↓             ↓
Access       Enter email or SSO
admin page   ↓
             Get OTP / SSO verify
             ↓
             Redirect to admin page
             with CF JWT cookie
             ↓
             Backend receives:
             Cookie: CF_Authorization_Token=...
             Header: Cf-Access-Jwt-Assertion=...
             ↓
             (Optional) Backend validates JWT
             ↓
             Access granted to /admin
```

---

## 3. Backend CF JWT Validation (Optional)

### 3.1. Why validate in backend?

- **Extra security layer:** Don't rely only on CF edge
- **Verification:** Ensure token is genuine, not tampered
- **Audit:** Log authenticated access attempts

### 3.2. Implement CF JWT validation

**File:** `/backend/app/auth.py`

Add CF JWT validation function:

```python
import os
from datetime import datetime, timezone
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt
from fastapi import HTTPException

CF_CERTS_URL = "https://cloudflare-dns.com/cdn-cgi/access/certs"

async def get_cf_public_keys():
    """Fetch Cloudflare's public keys for JWT verification."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(CF_CERTS_URL, timeout=5.0)
        resp.raise_for_status()
        return resp.json()

async def validate_cf_jwt(token: str, audience: str = None):
    """
    Validate Cloudflare Access JWT token.
    
    Args:
        token: JWT from Cf-Access-Jwt-Assertion header
        audience: Expected audience (your Cloudflare app UUID)
    
    Returns:
        Decoded token payload if valid
        
    Raises:
        HTTPException(401) if invalid or expired
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing CF JWT")
    
    try:
        # Get CF public keys
        keys = await get_cf_public_keys()
        
        # Decode JWT header to find which key was used
        unverified = jwt.decode(token, options={"verify_signature": False})
        kid = unverified.get("kid")
        
        if not kid:
            raise HTTPException(status_code=401, detail="JWT missing key ID")
        
        # Find the correct public key
        pub_key = None
        for key_data in keys.get("certs", []):
            if key_data.get("kid") == kid:
                pub_key = key_data.get("cert")
                break
        
        if not pub_key:
            raise HTTPException(status_code=401, detail="CF key not found")
        
        # Verify JWT signature
        payload = jwt.decode(
            token,
            pub_key,
            algorithms=["RS256"],
            audience=audience or None,
            options={"verify_exp": True}
        )
        
        return payload
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="CF JWT expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid CF JWT: {e}")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"CF JWT validation failed: {e}")

async def require_cf_auth(request: Request) -> dict:
    """
    Dependency for routes that require CF Access authentication.
    
    Extracts and validates CF JWT from request headers.
    """
    from fastapi import Request
    
    token = request.headers.get("Cf-Access-Jwt-Assertion")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Validate token
    payload = await validate_cf_jwt(token)
    
    return {
        "user": payload.get("email"),
        "identity": payload.get("identity_nonce"),
        "authenticated": True
    }
```

### 3.3. Apply CF JWT validation to admin routes

**File:** `/backend/app/main.py`

Update admin router registration to require CF JWT:

```python
from fastapi import Depends, Request
from app.auth import require_cf_auth

# In create_app() or route definition:

if settings.app_mode != "public":
    # For internal mode, require CF JWT on admin endpoints
    @app.get("/admin/health")
    async def admin_health_check(cf_auth: dict = Depends(require_cf_auth)):
        """Health check endpoint; requires CF Access authentication."""
        return {
            "status": "ok",
            "authenticated_user": cf_auth.get("user"),
            "app_mode": settings.app_mode
        }
    
    # Include admin router with CF auth dependency
    app.include_router(
        admin_router,
        prefix="/api/admin",
        dependencies=[Depends(require_cf_auth)]  # Protect all admin routes
    )
```

**Or protect individual routes:**

```python
from fastapi import APIRouter, Depends

admin_router = APIRouter()

@admin_router.get("/stats")
async def get_stats(cf_auth: dict = Depends(require_cf_auth)):
    """Get admin stats; requires CF Access."""
    user = cf_auth.get("user")
    # Log authenticated access
    logger.info(f"Admin stats accessed by {user}")
    return {"message": "stats", "user": user}
```

### 3.4. Test CF JWT validation

```bash
# 1. Get a real CF JWT (from browser after CF Access login)
# In browser DevTools Console:
// document.cookie will show: CF_Authorization_Token=...
// Or from request headers: Cf-Access-Jwt-Assertion

# 2. Test backend validation
curl -H "Cf-Access-Jwt-Assertion: <YOUR_JWT>" \
  http://localhost:8000/api/admin/stats

# Expected: 200 with stats
# If invalid: 401 Unauthorized
```

---

## 4. Configuration

### 4.1. Environment variables (optional)

Add to `.env`:

```bash
# CF Access verification (optional; if not set, CF JWT validation is disabled)
CF_AUTH_DOMAIN=https://sebastiaandenboer.org
CF_AUTH_AUDIENCE=<YOUR_CF_APP_UUID>
CF_CERTS_URL=https://cloudflare-dns.com/cdn-cgi/access/certs

# Admin email whitelist (alternative to CF Access)
ADMIN_EMAILS=your-email@domain.com,other-admin@domain.com
```

### 4.2. Cloudflare DNS records

Ensure DNS is set up:

```bash
# Type: CNAME
# Name: sebastiaandenboer.org
# Value: <YOUR_TUNNEL_ID>.cfargotunnel.com

# Type: CNAME
# Name: www.sebastiaandenboer.org
# Value: <YOUR_TUNNEL_ID>.cfargotunnel.com
```

---

## 5. Testing Admin Access

### 5.1. Before CF Access deployment (local)

Test admin endpoints locally:

```bash
# Start backend with APP_MODE=internal
export APP_MODE=internal
cd backend && python -m uvicorn app.main:app --reload

# Test public endpoint (no auth)
curl http://localhost:8000/api/chat -X POST -d '{"message": "test"}'
# Expected: 200

# Test admin endpoint (should be blocked or require token)
curl http://localhost:8000/api/admin/stats
# Expected: 401 (or public data only)
```

### 5.2. After CF Access deployment (production)

1. **Unauthenticated access:**
```bash
curl https://sebastiaandenboer.org/admin
# Expected: 302 redirect to CF login, or CF Access login page
```

2. **Authenticated access:**
- Visit `https://sebastiaandenboer.org/admin` in browser
- CF Access prompts for email/SSO
- You login and are redirected to admin panel
- Backend receives CF JWT in headers

3. **Public paths still work:**
```bash
curl https://sebastiaandenboer.org/api/chat
# Expected: 200 (public access, no auth)
```

---

## 6. Troubleshooting

### 6.1. "Unauthorized" on CF Access pages

- Check policy rules in CF dashboard
- Verify your email is in allow list
- Clear browser cookies: Settings → Privacy → Clear cookies

### 6.2. Backend rejects CF JWT

- Check JWT is in headers: `curl -v` to see headers
- Ensure `CF_AUTH_DOMAIN` is set correctly
- Verify CF public keys are accessible from backend
- Check JWT expiration (24 hours by default)

### 6.3. Admin endpoints still accessible without auth

- Verify `Depends(require_cf_auth)` is applied to routes
- Check that backend is reading `Cf-Access-Jwt-Assertion` header
- Ensure CF Edge is running (check tunnel status)

### 6.4. CF Access policy not enforcing

- Verify policy is enabled in CF dashboard
- Check policy priority (first match wins)
- Ensure domain DNS is pointing to CF Tunnel (not direct IP)

---

## 7. Security Best Practices

- [ ] Use email OTP or SSO; require multi-factor auth if available
- [ ] Set JWT expiration to reasonable value (24 hours)
- [ ] Enable CF WAF (Web Application Firewall) for additional protection
- [ ] Log all admin access (with username/timestamp)
- [ ] Rotate CF API tokens periodically
- [ ] Use CF Tunnel instead of exposing raw NAS ports
- [ ] Implement rate limiting on admin endpoints
- [ ] Regularly rotate access credentials
- [ ] Monitor CF Access logs for suspicious activity

---

## 8. Public vs. Admin Access Summary

| Endpoint | Public | Internal (no CF) | Internal (with CF) |
|---|---|---|---|
| `/` | ✓ Open | ✓ Open | ✓ Open |
| `/api/chat` | ✓ Open | ✓ Open | ✓ Open |
| `/api/knowledge/*` | Role-filtered | Full | Full |
| `/api/speak` | ✓ Open | ✓ Open | ✓ Open |
| `/api/transcribe` | ✓ Open | ✓ Open | ✓ Open |
| `/api/suggestions` | Role-filtered | Full | Full |
| `/api/admin/stats` | ❌ Not in public | ✓ Token auth | ✓ CF JWT + token auth |
| `/api/admin/sync` | ❌ Not in public | ✓ Token auth | ✓ CF JWT + token auth |
| `/admin` | ❌ Not in public | ✓ (open) | ✓ CF Access gate |

---

## 9. Deployment Checklist

- [ ] CF Access app created for `/admin` path
- [ ] CF Access policy configured (email OTP or SSO)
- [ ] CF policy rules limit to owner email(s)
- [ ] DNS CNAME records point to CF Tunnel
- [ ] Backend JWT validation configured (optional but recommended)
- [ ] Admin routes include `Depends(require_cf_auth)` in internal mode
- [ ] TEST: Unauthenticated user cannot access `/admin` (CF blocks)
- [ ] TEST: Authenticated user can access `/admin` (with token)
- [ ] TEST: Public paths still accessible without auth
- [ ] TEST: Public deployment mode doesn't include admin routes
- [ ] Monitoring enabled for admin access attempts
- [ ] Logging configured for CF Access events

---

## 10. Reference: CF Access Configuration Examples

### 10.1. Email OTP policy

```yaml
Policy Name: Owner Email OTP
Conditions:
  - Email domain matches: @sebastiaandenboer.org
  - OR Email is: your-personal-email@gmail.com
Authentication: Email OTP
Approval: Not required
```

### 10.2. Google SSO + email policy

```yaml
Policy Name: Owner Accounts
Conditions:
  - Email is: you@gmail.com (Google)
  - AND Country is: NL (optional)
Authentication: Google OAuth + Email
Approval: Not required
```

### 10.3. SAML + IP whitelist

```yaml
Policy Name: VPN + SAML
Conditions:
  - IP ranges include: 192.168.0.0/16 (your home network)
  - AND SAML group: admins
Authentication: SAML
Approval: Not required
```

---

## 11. Monitoring & Logging

### 11.1. View CF Access logs

In CF dashboard:

1. **Analytics** → **Access** → **Users**
   - See all login attempts
   - Timestamp, email, status
   - Successful and failed attempts

2. **Analytics** → **Access** → **Audit logs**
   - Policy changes
   - Application modifications
   - Team member changes

### 11.2. Log admin access in backend

Update your logging:

```python
# In admin route handlers
async def admin_stats(cf_auth: dict = Depends(require_cf_auth)):
    user = cf_auth.get("user")
    identity = cf_auth.get("identity_nonce")
    
    logger.info(f"Admin access granted to {user} (identity: {identity})")
    
    # Your admin logic here
    return {"stats": {...}}
```

---

## 12. Future Enhancements

- [ ] Device posture checks (only allow from trusted devices)
- [ ] Geo-blocking (only allow logins from specific countries)
- [ ] Time-based access (only allow 9-5 M-F)
- [ ] Hardware security key enforcement
- [ ] Automated session timeout on inactivity
- [ ] Integration with Cloudflare WAF for rate limiting
