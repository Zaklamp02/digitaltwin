# Admin Hardening Deployment Checklist

**Objective:** Complete admin access control hardening for the Digital Twin before public launch.

**Timeline:** Prior to NAS deployment  
**Responsible:** Owner  
**Verification:** Manual testing + CF dashboard validation

---

## Phase 1: Backend Code Hardening

### 1.1. CF JWT validation code

- [x] Added `CFAccessIdentity` dataclass to `auth.py`
- [x] Added `validate_cf_jwt()` function with async JWT verification
- [x] Added `cf_access_dep` FastAPI dependency for route protection
- [x] Added fallback for missing pyjwt library
- [x] Added comprehensive logging for JWT validation

**Code locations:**
- `/backend/app/auth.py` — CF JWT functions
- `/backend/tests/test_auth.py` — Unit tests for CF validation

### 1.2. Dependencies

- [x] Added `pyjwt>=2.8` to `backend/pyproject.toml`
- [x] Added `cryptography>=41.0` to `backend/pyproject.toml`
- [x] `httpx>=0.27` already in dependencies (needed for CF certs fetch)

**Verify dependencies:**
```bash
cd backend
pip install pyjwt>=2.8 cryptography>=41.0
# or
pip install -e .
```

### 1.3. Update admin routes to use CF auth

- [ ] Update `/backend/app/main.py` to include `Depends(cf_access_dep)` in admin routes (when deploying internal stack)
- [ ] Add CF JWT header validation to `/api/admin/*` endpoints
- [ ] Test that admin routes reject requests without CF header (401)

**Example:**
```python
from app.auth import cf_access_dep, CFAccessIdentity
from fastapi import Depends

@admin_router.get("/stats")
async def get_stats(cf_auth: CFAccessIdentity = Depends(cf_access_dep)):
    """Admin stats endpoint; requires CF Access authentication."""
    return {"authenticated_user": cf_auth.email}
```

### 1.4. Logging

- [ ] Verify that all admin access attempts are logged with timestamp and user email
- [ ] Review log output format in `logs/requests.ndjson` (should include admin access)

---

## Phase 2: Cloudflare Access Setup

### 2.1. Create CF Access application

- [ ] Open Cloudflare dashboard → Zero Trust → Access → Applications
- [ ] Create new application: `digital-twin-admin`
- [ ] Set domain: `sebastiaandenboer.org`
- [ ] Set path: `/admin`
- [ ] Application type: `Self-hosted`

### 2.2. Configure authentication policy

- [ ] Create policy: `admin-owner-only`
- [ ] **Option A (recommended):** Email OTP
  - [ ] Add email OTP as authentication method
  - [ ] Add rule: "Allow if email is <YOUR_EMAIL>"
  
- [ ] **Option B:** Google/GitHub SSO
  - [ ] Connect social provider
  - [ ] Add rule: "Allow if social account is <YOUR_ACCOUNT>"

- [ ] Set JWT expiration: 24 hours
- [ ] Enable auto-redirect if already authenticated

### 2.3. Create second CF Access app for API endpoints

- [ ] Create application: `digital-twin-admin-api`
- [ ] Set domain: `sebastiaandenboer.org`
- [ ] Set path: `/api/admin`
- [ ] Apply same authentication policy as `/admin`

### 2.4. Verify CF DNS routing

- [ ] Check DNS CNAME records are set:
  ```
  sebastiaandenboer.org  CNAME  <TUNNEL_ID>.cfargotunnel.com
  www.sebastiaandenboer.org CNAME <TUNNEL_ID>.cfargotunnel.com
  ```
- [ ] Verify CF tunnel is running and healthy

---

## Phase 3: Local Testing

### 3.1. Test without CF Access (dev environment)

```bash
# Start backend in internal mode (no CF yet)
export APP_MODE=internal
cd backend && python -m uvicorn app.main:app --reload

# Test public endpoint (no auth, should work)
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}'
# Expected: 200

# Test admin endpoint without token
curl http://localhost:8000/api/admin/stats
# Expected: 401 (unless CF JWT validation is disabled in dev)
```

### 3.2. Test with CF JWT mock (dev environment)

```bash
# Create a mock CF JWT for testing
# (See test_auth.py for how to generate a valid JWT)

# Test admin endpoint with mock CF JWT
curl -H "Cf-Access-Jwt-Assertion: <MOCK_JWT>" \
  http://localhost:8000/api/admin/stats
# Expected: 200 with stats
```

### 3.3. Test public paths still accessible

```bash
# These should be accessible WITHOUT any token
curl https://localhost:8000/api/chat
curl https://localhost:8000/api/knowledge/node/...
curl https://localhost:8000/api/speak
curl https://localhost:8000/api/transcribe
```

---

## Phase 4: NAS Deployment Testing

### 4.1. Deploy internal and public stacks to NAS

```bash
# From dev machine
make deploy-stacks

# Verify both stacks are running
make status
```

### 4.2. Test public deployment (no admin access)

```bash
# From any internet-connected device
curl https://sebastiaandenboer.org/api/admin/stats
# Expected: 401 or 403 (admin routes not in public stack)

# Public paths should work
curl https://sebastiaandenboer.org/api/chat
# Expected: 200
```

### 4.3. Test internal deployment (CF Access gate)

**Without authentication:**
```bash
# Try to access admin without CF JWT
curl -v https://internal.sebastiaandenboer.org/admin
# Expected: 302 redirect to CF login page
# OR: CF Access login page in browser
```

**With authentication:**
1. Navigate to `https://internal.sebastiaandenboer.org/admin` in browser
2. CF Access prompts for email/SSO
3. Enter credentials (email OTP or social SSO)
4. Redirected to admin panel
5. Backend receives CF JWT in headers
6. Admin routes are accessible

**Verify headers:**
```bash
# After logging in via CF Access, check headers in browser
# Open DevTools → Network → Click on request → Headers
# Should see:
# Cookie: CF_Authorization_Token=...
# Or header: Cf-Access-Jwt-Assertion=...
```

### 4.4. Test NAS internal access (LAN-only)

```bash
# From NAS or LAN client (with token auth)
curl -H "X-Access-Token: <YOUR_TOKEN>" \
  http://nas.local:8081/api/admin/stats
# Expected: 200

# Without token
curl http://nas.local:8081/api/admin/stats
# Expected: 401 (token auth required, even on LAN)
```

---

## Phase 5: Security Verification

### 5.1. Verify admin routes are excluded from public stack

```bash
# SSH to NAS
ssh <NAS_USER>@<NAS_IP>

# Check public app mode
cd /volume1/docker/digital_twin_public
docker compose exec -T backend-public \
  python -c "from app.config import get_settings; print(get_settings().app_mode)"
# Expected: "public"

# Verify admin routes don't exist in public app
docker compose exec -T backend-public \
  curl -s http://localhost:8000/api/admin/stats | head
# Expected: 404 or 405 (route not found/not allowed)
```

### 5.2. Verify internal routes are protected by CF Access

```bash
# From browser, try to access without logging in
curl -v https://sebastiaandenboer.org/admin
# Expected: CF Access login page (302 redirect or form)

# From command line without CF headers
curl -v https://sebastiaandenboer.org/admin
# Expected: 401 or CF login page (not admin panel)
```

### 5.3. Verify token rotation works

```bash
# Generate new token in credentials.yaml
# Restart backend
cd /volume1/docker/digital_twin_internal
docker compose restart backend-internal

# Test with new token
curl -H "X-Access-Token: <NEW_TOKEN>" \
  http://nas.local:8081/api/admin/stats
# Expected: 200

# Test with old token (should fail if no longer in credentials.yaml)
curl -H "X-Access-Token: <OLD_TOKEN>" \
  http://nas.local:8081/api/admin/stats
# Expected: 401 (invalid token)
```

### 5.4. Verify rate limiting still works

```bash
# Hammer admin endpoint to verify rate limits
for i in {1..30}; do
  curl -H "X-Access-Token: <YOUR_TOKEN>" \
    http://nas.local:8081/api/admin/stats
done
# After limit exceeded: 429 (Too Many Requests)
```

---

## Phase 6: Monitoring & Logging

### 6.1. Enable CF Access audit logging

In Cloudflare dashboard:

1. **Analytics** → **Access** → **Audit logs**
2. Verify login attempts, policy changes, and access events are logged
3. Set up email notifications for failed logins (optional)

### 6.2. Monitor backend admin access logs

```bash
# SSH to NAS and check admin access logs
ssh <NAS_USER>@<NAS_IP>

# View admin endpoint access
tail -f /volume1/docker/digital_twin_internal/logs_internal/requests.ndjson | \
  grep "/api/admin"

# Example log entry:
# {
#   "timestamp": "2026-05-08T10:30:00Z",
#   "path": "/api/admin/stats",
#   "method": "GET",
#   "status": 200,
#   "caller": "pers-xyz",
#   "email": "user@cloudflare"  (if CF JWT validation enabled)
# }
```

### 6.3. Set up alerts (optional)

- [ ] Slack/email notification on admin access failures
- [ ] Alert if CF Access policy changes
- [ ] Monitor backend error logs for failed JWT validations

---

## Phase 7: Documentation

### 7.1. Update README

- [ ] Add section: "Admin Access" with CF Access login URL
- [ ] Document internal vs. public deployment modes
- [ ] Link to `ADMIN_HARDENING_CLOUDFLARE_ACCESS.md`

### 7.2. Update deployment docs

- [ ] Add CF Access setup steps to `NAS_DEPLOYMENT_INTERNAL.md`
- [ ] Update internal stack ports (should use tunnel, not raw port)
- [ ] Document token rotation process

### 7.3. Create admin runbook

- [ ] How to log in via CF Access
- [ ] How to rotate admin tokens
- [ ] How to troubleshoot access issues
- [ ] Emergency admin access procedure (if CF is down)

---

## Phase 8: Final Validation Checklist

Before marking admin hardening complete, verify:

### Security

- [ ] Public app mode doesn't include admin routes (verified in code + tested)
- [ ] Admin routes require either CF JWT (production) or token (LAN)
- [ ] CF Access policies restrict to owner email only
- [ ] Tokens are rotated (old production tokens discarded)
- [ ] No admin credentials in git history (gitleaks clean)

### Functionality

- [ ] Public users cannot access `/admin` (get 401/403)
- [ ] Owner can access `/admin` after CF Access login
- [ ] Admin endpoints work correctly (stats, sync, etc.)
- [ ] Public paths still work without authentication
- [ ] Rate limiting works on admin endpoints

### Deployment

- [ ] Public stack running with `APP_MODE=public`
- [ ] Internal stack running with `APP_MODE=internal` (or `internal-cf` if CF JWT enabled)
- [ ] CF tunnel configured and healthy
- [ ] CF Access policies active and enforced
- [ ] NAS firewall doesn't expose ports directly (all via tunnel)

### Monitoring

- [ ] CF Access audit logs are being recorded
- [ ] Backend admin access logs are being written
- [ ] No errors in backend logs related to CF JWT validation
- [ ] Alerting configured for admin access failures

### Documentation

- [ ] Admin access instructions documented
- [ ] CF Access setup procedure documented
- [ ] Troubleshooting guide created
- [ ] Owner familiar with emergency admin access procedure

---

## Rollback Procedure

If CF Access fails or becomes unavailable:

### Option 1: Use LAN-only access (temporary)

```bash
# Access internal stack from LAN with token auth
curl -H "X-Access-Token: <YOUR_TOKEN>" \
  http://nas.local:8081/admin
```

### Option 2: Bypass CF Access (emergency only)

```bash
# Update CF policy to allow all (remove restrictions)
# OR
# Update backend to not require CF JWT (temporary)

# Then restore CF Access when issue is resolved
```

### Option 3: Direct NAS access (if tunnel fails)

```bash
# SSH to NAS and run admin commands directly
ssh <NAS_USER>@<NAS_IP>
cd /volume1/docker/digital_twin_internal
docker compose exec backend-internal python scripts/admin_command.py
```

---

## Success Criteria

You have successfully hardened admin access when:

1. ✅ Public deployment has NO admin routes registered
2. ✅ Internal deployment requires CF Access auth for `/admin` paths
3. ✅ Only owner email can access admin panel
4. ✅ All admin access is logged with CF JWT identity
5. ✅ Tokens are securely stored and rotated before public launch
6. ✅ Public users cannot discover or access admin functionality
7. ✅ Owner can quickly regain admin access even if CF goes down (LAN token auth fallback)

---

## Timeline

| Phase | Duration | Owner | Approval |
|---|---|---|---|
| Phase 1: Code hardening | 30 min | Dev | Code review |
| Phase 2: CF Access setup | 15 min | Admin | CF dashboard |
| Phase 3: Local testing | 30 min | QA | Test results |
| Phase 4: NAS deployment | 30 min | DevOps | Deployment logs |
| Phase 5: Security verification | 60 min | Security | Checklist |
| Phase 6: Monitoring | 30 min | Ops | Alerts configured |
| Phase 7: Documentation | 30 min | Tech writer | Docs reviewed |
| Phase 8: Final validation | 30 min | All | All items checked |
| **TOTAL** | **~4 hours** | **Cross-team** | **Go/No-go** |

---

## Sign-off

- [ ] All phases completed
- [ ] All checklist items verified
- [ ] Owner has tested admin access flow
- [ ] Backup access procedures documented and tested
- [ ] Security review passed
- [ ] Ready for public launch

**Date completed:** ________________  
**Verified by:** ________________  
**Notes:** 

