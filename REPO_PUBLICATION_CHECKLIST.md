# Repository Publication Scrubbing Guide

**Objective:** Ensure the repository is safe to publish publicly by:
1. Scanning for accidental secret commits in git history
2. Identifying and removing operational docs that expose NAS/infrastructure details
3. Validating `.gitignore` effectiveness
4. Creating public and private versions of documentation

**Status:** Pre-public-launch checklist

---

## 1. Secrets Detection & Remediation

### 1.1. Install and run gitleaks

```bash
# Install gitleaks (macOS)
brew install gitleaks

# Scan entire git history for secret patterns
cd /path/to/Digital\ Twin
gitleaks detect --verbose --report-path /tmp/gitleaks-report.json

# View results
cat /tmp/gitleaks-report.json | jq '.'
```

**Expected findings:**
- None, if `.env` and `credentials.yaml` were always in `.gitignore`
- If secrets are found, they must be removed from git history before public launch

### 1.2. Secret patterns to detect (in .gitleaks.toml)

The following patterns should trigger alerts:

- `ANTHROPIC_API_KEY` (e.g., `sk-...`)
- `OPENAI_API_KEY` (e.g., `sk-...`)
- `TELEGRAM_BOT_TOKEN` (numeric:token format)
- Cloudflare API tokens (Bearer tokens in config)
- NAS SSH keys (private keys in `.cloudflared/`)
- Database connection strings with passwords
- URL fragments/query params with tokens (e.g., `?t=`, `#t=`)

### 1.3. If secrets are found in history

If `gitleaks` detects secrets already committed:

```bash
# Option 1: Force push to remove (if this is safe in your workflow)
git filter-branch --tree-filter 'rm -f .env credentials.yaml .cloudflared/*.json' HEAD

# Option 2: Use git-filter-repo (recommended, more reliable)
pip install git-filter-repo
git filter-repo --path .env --invert-paths
git filter-repo --path credentials.yaml --invert-paths
git filter-repo --path .cloudflared --invert-paths

# Verify secrets are gone
gitleaks detect --report-path /tmp/gitleaks-report-after.json
cat /tmp/gitleaks-report-after.json | grep -c findings
# → Should output 0
```

### 1.4. Rotate credentials

Even if secrets were accidentally committed and then removed, assume they may have been exposed:

```bash
# Before public launch, rotate:
# 1. ANTHROPIC_API_KEY — regenerate in Anthropic dashboard
# 2. OPENAI_API_KEY — regenerate in OpenAI dashboard
# 3. TELEGRAM_BOT_TOKEN — request new bot token from BotFather
# 4. Cloudflare API token — regenerate in CF dashboard
# 5. NAS SSH keys — regenerate authorized_keys if ever in git history
```

---

## 2. Documentation Scrubbing

### 2.1. Documents to sanitize for public

| Document | Concern | Action |
|---|---|---|
| `DEPLOY_PRD.md` | NAS IP (192.168.68.200), paths (`/volume1/docker/`), Tunnel ID | Create public version with placeholders |
| `NAS_DEPLOYMENT.md` | Same as above | Create public version; keep detailed internal version private |
| `.env` (if leaked) | All API keys, sensitive URLs | Keep private in `.gitignore` |
| `credentials.yaml` (if leaked) | All tokens, secrets | Keep private in `.gitignore` |
| `.cloudflared/` (if leaked) | Tunnel credentials, cert | Keep private in `.gitignore` |

### 2.2. Public-safe versions of docs

Create:
- `DEPLOY_PRD.md` → keep as-is (already contains placeholders and design docs)
- `NAS_DEPLOYMENT.md` → create `NAS_DEPLOYMENT_INTERNAL.md` (current, detailed), create public `NAS_DEPLOYMENT_PUBLIC.md` (sanitized)
- `README.md` → already safe; verify no IPs or credentials

### 2.3. Sanitization template

For `NAS_DEPLOYMENT_PUBLIC.md`:

```markdown
# NAS Dual-Runtime Deployment Guide (Public)

**Note:** This is a template. Replace placeholder values with your own infrastructure details.

**Objective:** Run the Digital Twin on a home NAS with public and internal runtimes.

**Your setup:**
- NAS Host: `<YOUR_NAS_IP>`
- Deploy directory: `<YOUR_DEPLOY_PATH>` (e.g., `/volume1/docker/`)
- Domain: `<YOUR_DOMAIN>` (e.g., `your-domain.com`)

---

## 1. Deployment Architecture Overview

```
Your NAS (at <YOUR_NAS_IP>)
│
├─ Public Runtime
│  ├─ Frontend: port <YOUR_PUBLIC_PORT> (typically 8080)
│  ├─ Backend: APP_MODE=public
│  └─ Tunnel: Via Cloudflare to <YOUR_DOMAIN>
│
└─ Internal Runtime
   ├─ Frontend: port <YOUR_INTERNAL_PORT> (typically 8081)
   ├─ Backend: APP_MODE=internal
   └─ Access: LAN-only, token auth
```

...
```

### 2.4. Create .gitignore audit

Verify critical files are excluded:

```bash
# Check that secrets are properly ignored
git check-ignore -v .env credentials.yaml .cloudflared/ logs/ chroma_db/ data/

# Expected output (all should be ignored):
.env
credentials.yaml
.cloudflared/
logs/
chroma_db/
data/
vault/
```

---

## 3. Public Repository Checklist

Before pushing to a public repo, verify:

### 3.1. Secrets audit

- [ ] Run `gitleaks detect` — **0 findings**
- [ ] `.env` is in `.gitignore` and not committed
- [ ] `credentials.yaml` is in `.gitignore` and not committed
- [ ] `.cloudflared/` is in `.gitignore` and not committed
- [ ] No API keys in any markdown files or config examples
- [ ] No NAS SSH private keys anywhere
- [ ] `tokens.txt` (if it exists) is in `.gitignore`

### 3.2. Infrastructure audit

- [ ] No hardcoded NAS IP addresses (except in private docs like `NAS_DEPLOYMENT_INTERNAL.md`)
- [ ] No hardcoded Cloudflare Tunnel IDs
- [ ] No hardcoded SSH usernames (`Storybrew@...`)
- [ ] No hardcoded paths that expose NAS structure
- [ ] No absolute paths that reveal personal directory structure

Example of **unsafe** (exposes infrastructure):
```markdown
ssh Storybrew@192.168.68.200:/volume1/docker/digital_twin_internal/
```

Example of **safe** (generic placeholder):
```markdown
ssh <NAS_USER>@<NAS_IP>:/<NAS_DEPLOY_PATH>/internal/
```

### 3.3. Code audit

- [ ] No test tokens in `tests/conftest.py` or test fixtures (use dummy values)
- [ ] No hardcoded URLs pointing to 192.168.x.x
- [ ] No comments with credentials or secrets
- [ ] No TODO comments revealing security weaknesses

### 3.4. .gitignore validation

```bash
# Files that MUST be ignored (checked in .gitignore or .git/info/exclude)
git status --ignored | grep -E '\.env|credentials|\.cloudflared|tokens\.txt|data/|chroma_db|logs'
# → Should return nothing (all ignored)
```

---

## 4. Public vs. Private Documentation

### 4.1. Files to keep private (not in public repo)

- `NAS_DEPLOYMENT_INTERNAL.md` — Full NAS setup with IP addresses and paths
- `.env` — Never commit (in `.gitignore`)
- `credentials.yaml` — Never commit (in `.gitignore`)
- `.cloudflared/` — Never commit (in `.gitignore`)
- `tokens.txt` — Never commit (in `.gitignore`)
- `TEAMS_SETUP.md` — If it contains hardcoded webhook URLs or team IDs

### 4.2. Files safe for public repo

- `README.md` — General info; verify no credentials
- `DEPLOY_PRD.md` — Already uses placeholders
- `RUN_LOCALLY.md` — Local dev guide; already safe
- `docker-compose.yml` — Dev/local; never contains secrets
- `docker-compose.public.yml` — Generic template; no secrets
- `docker-compose.internal.yml` — Generic template; no secrets
- `NAS_DEPLOYMENT_PUBLIC.md` — Sanitized version with placeholders
- `Makefile` — Generic commands; verify no hardcoded IPs/tokens
- All source code (`backend/`, `frontend/`) — Verify no hardcoded URLs/keys

### 4.3. Create private documentation repo (optional)

If you want to keep detailed ops docs in version control but private:

```bash
# Create a separate private repo for ops/infrastructure docs
git init ~/Documents/Digital-Twin-Ops (private)
git remote add origin <private-repo-url>

# Copy sensitive docs there
cp NAS_DEPLOYMENT_INTERNAL.md ~/Documents/Digital-Twin-Ops/
cp .env ~/Documents/Digital-Twin-Ops/.env.template (with placeholders)
cp TEAMS_SETUP.md ~/Documents/Digital-Twin-Ops/
```

---

## 5. Pre-Public Launch Checklist

### 5.1. Run automated scans

```bash
# 1. Gitleaks scan
gitleaks detect --report-path /tmp/gitleaks-report.json
echo "Gitleaks findings: $(jq '.Results | length' /tmp/gitleaks-report.json)"

# 2. Check .gitignore coverage
git status --ignored | wc -l
echo "Ignored files: $(git status --ignored | wc -l)"

# 3. Search for suspicious patterns in tracked files
git ls-tree -r HEAD --name-only | while read file; do
  grep -l 'API_KEY\|SECRET\|TOKEN\|PASSWORD\|192\.168\|@' "$file" 2>/dev/null || true
done | grep -v node_modules | sort -u
```

### 5.2. Manual review

```bash
# Check sensitive files one more time
git status
git diff --cached

# Review docs for hardcoded values
grep -r '192\.168\.' . --include='*.md' --include='*.py' --include='*.ts' --include='*.tsx'
grep -r 'Storybrew@' . --include='*.md' --include='*.py'
grep -r '/volume1/docker' . --include='*.md' --include='*.py'
grep -r 'ANTHROPIC_API_KEY\|OPENAI_API_KEY\|TELEGRAM_BOT_TOKEN' . --include='*.md' --include='*.py' --include='*.tsx'
```

### 5.3. Commit and tag

```bash
# Final cleanup and commit
git add .gitignore README.md DEPLOY_PRD.md NAS_DEPLOYMENT_PUBLIC.md
git commit -m "chore: pre-public-launch scrubbing (no ops details, no credentials)"

# Tag as a public release
git tag -a v1.0.0-public -m "First public release; all secrets scrubbed"
```

---

## 6. Ongoing Maintenance

After public launch, maintain security hygiene:

- [ ] Run `gitleaks` on every CI/CD build (catch accidental commits)
- [ ] Weekly `.gitignore` audit (verify secrets not leaking)
- [ ] Rotate API keys quarterly
- [ ] Monitor GitHub for commits that accidentally push secrets (GitHub's own native detector will alert)
- [ ] Never share NAS SSH keys, tunnel IDs, or infrastructure details in issues/PRs

---

## 7. Quick Reference: Dangerous Patterns

| Pattern | Severity | Example | Safe Alternative |
|---|---|---|---|
| Hardcoded IPs | 🔴 High | `192.168.68.200` | Use `<YOUR_NAS_IP>` placeholder |
| NAS usernames | 🔴 High | `Storybrew@192.168...` | Use `<NAS_USER>@<NAS_IP>` |
| API keys | 🔴 High | `sk-proj-abc123...` | Never commit; use `.env` |
| Tunnel IDs | 🔴 High | `34e7de3b-3768-47f8...` | Never commit; use `.cloudflared/config.yml` |
| NAS paths | 🟡 Medium | `/volume1/docker/digital_twin` | Use generic `<NAS_DEPLOY_PATH>` |
| Tokens in docs | 🟡 Medium | `curl ?t=sk-abc123` | Use `?t=<YOUR_TOKEN>` |
| Webhook URLs | 🟡 Medium | `https://teams.microsoft.com/webhook/...` | Move to private docs |
| SSH keys | 🔴 High | Private key contents | Never commit; store securely |

---

## 8. Tool: Automated Scrubbing Script

Create `scripts/pre-public-check.sh`:

```bash
#!/bin/bash
set -e

echo "🔍 Pre-public launch security audit..."

# 1. Gitleaks
echo "[1/5] Running gitleaks..."
gitleaks detect --report-path /tmp/gitleaks-report.json -v
FINDINGS=$(jq '.Results | length' /tmp/gitleaks-report.json || echo 0)
if [ $FINDINGS -gt 0 ]; then
  echo "❌ FAIL: Gitleaks found $FINDINGS potential secrets!"
  jq '.Results[] | {File: .File, Secret: .Secret}' /tmp/gitleaks-report.json
  exit 1
fi
echo "✓ No secrets detected"

# 2. Check .gitignore coverage
echo "[2/5] Checking .gitignore coverage..."
for pattern in '.env' 'credentials.yaml' '.cloudflared' 'tokens.txt'; do
  if ! git check-ignore $pattern > /dev/null 2>&1; then
    echo "❌ FAIL: $pattern is not properly ignored!"
    exit 1
  fi
done
echo "✓ All secrets files properly ignored"

# 3. Search for suspicious patterns
echo "[3/5] Searching for suspicious patterns..."
SUSPICIOUS=$(git ls-tree -r HEAD --name-only | xargs grep -l \
  'ANTHROPIC_API_KEY\|OPENAI_API_KEY\|TELEGRAM_BOT_TOKEN\|192\.168\.68\.\|Storybrew@' \
  2>/dev/null | grep -v node_modules | wc -l)
if [ $SUSPICIOUS -gt 0 ]; then
  echo "❌ FAIL: Found $SUSPICIOUS files with suspicious patterns!"
  exit 1
fi
echo "✓ No hardcoded credentials or IPs in committed files"

# 4. Check for uncommitted secrets
echo "[4/5] Checking for uncommitted secrets in working directory..."
if [ -f .env ] && git diff --cached --name-only | grep -q '\.env'; then
  echo "❌ FAIL: .env is staged for commit!"
  exit 1
fi
if [ -f credentials.yaml ] && git diff --cached --name-only | grep -q 'credentials'; then
  echo "❌ FAIL: credentials.yaml is staged for commit!"
  exit 1
fi
echo "✓ No secrets staged for commit"

# 5. Verify docs are sanitized
echo "[5/5] Verifying documentation is sanitized..."
if ! grep -q '<YOUR_NAS_IP>' README.md 2>/dev/null; then
  echo "⚠️  WARNING: README.md should have placeholder IPs, verify manually"
fi
echo "✓ Documentation checked"

echo ""
echo "✅ All checks passed! Safe for public push."
echo ""
echo "Next steps:"
echo "  1. Review git diff one final time: git diff HEAD"
echo "  2. Push to public repo: git push origin main --tags"
```

Make it executable:

```bash
chmod +x scripts/pre-public-check.sh
```

Run before public launch:

```bash
./scripts/pre-public-check.sh
```

---

## 9. Cloudflare Tunnel & DNS

### 9.1. Security considerations

- **Tunnel credentials:** Store only in `~/.cloudflared/` (never in Git)
- **DNS records:** Use CNAME to Cloudflare (not A records with NAS IP)
- **Tunnel UUID:** Not sensitive, but don't hardcode in code; keep in config files

### 9.2. Verify Cloudflare setup

```bash
# List tunnels (should show your digital-twin tunnels)
cloudflared tunnel list

# View active tunnels
cloudflared tunnel route
```

---

## 10. GitHub-specific Security

If using GitHub for public hosting:

- [ ] Enable "Secret scanning" in repo settings
- [ ] Enable "Push protection" (prevents commits with secrets)
- [ ] Add branch protection rules (require PR review before merge)
- [ ] Rotate any GitHub PAT (personal access tokens) used in workflows
- [ ] Review GitHub Actions for hardcoded credentials (check `.github/workflows/`)

