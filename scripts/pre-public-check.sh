#!/bin/bash
# Pre-public launch security audit script
# Run this before publishing the repository publicly

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "🔍 Digital Twin: Pre-public launch security audit"
echo ""

FAILED=0

# 1. Gitleaks scan
echo "[1/6] Running gitleaks for secret detection..."
if command -v gitleaks &> /dev/null; then
  gitleaks detect --config .gitleaks.toml --verbose --report-path /tmp/gitleaks-report.json 2>&1 | head -20
  FINDINGS=$(jq '.Results | length' /tmp/gitleaks-report.json 2>/dev/null || echo 0)
  if [ $FINDINGS -gt 0 ]; then
    echo -e "${RED}❌ FAIL: Gitleaks found $FINDINGS potential secrets!${NC}"
    jq '.Results[] | {File: .File, Secret: .Secret, Line: .StartLine}' /tmp/gitleaks-report.json 2>/dev/null | head -10
    FAILED=$((FAILED + 1))
  else
    echo -e "${GREEN}✓ No secrets detected${NC}"
  fi
else
  echo -e "${YELLOW}⚠️  gitleaks not installed. Install: brew install gitleaks${NC}"
fi

# 2. Check .gitignore coverage
echo ""
echo "[2/6] Checking .gitignore coverage..."
IGNORE_FAILED=0
for pattern in '.env' 'credentials.yaml' '.cloudflared' 'tokens.txt'; do
  if ! git check-ignore "$pattern" > /dev/null 2>&1; then
    echo -e "${RED}❌ $pattern is not properly ignored!${NC}"
    IGNORE_FAILED=$((IGNORE_FAILED + 1))
  fi
done

if [ $IGNORE_FAILED -eq 0 ]; then
  echo -e "${GREEN}✓ All secrets files properly ignored${NC}"
else
  FAILED=$((FAILED + 1))
fi

# 3. Search for suspicious patterns in committed files
echo ""
echo "[3/6] Searching for suspicious patterns in tracked files..."
SUSPICIOUS_FILES=$(mktemp)
git ls-tree -r HEAD --name-only 2>/dev/null | while read file; do
  # Skip binary files and node_modules
  if [[ "$file" == *"node_modules"* ]] || [[ "$file" == *".git"* ]] || [[ "$file" == *"dist"* ]]; then
    continue
  fi
  if git show "HEAD:$file" 2>/dev/null | grep -qiE 'ANTHROPIC_API_KEY|OPENAI_API_KEY|TELEGRAM_BOT_TOKEN|sk-proj-|sk-ant-|Bearer\s+[a-z0-9]{40,}'; then
    echo "$file" >> "$SUSPICIOUS_FILES"
  fi
done

if [ -f "$SUSPICIOUS_FILES" ] && [ -s "$SUSPICIOUS_FILES" ]; then
  COUNT=$(wc -l < "$SUSPICIOUS_FILES")
  echo -e "${RED}❌ Found $COUNT files with suspicious patterns:${NC}"
  head -5 "$SUSPICIOUS_FILES"
  FAILED=$((FAILED + 1))
else
  echo -e "${GREEN}✓ No hardcoded API keys in committed files${NC}"
fi
rm -f "$SUSPICIOUS_FILES"

# 4. Check for NAS IPs in documentation
echo ""
echo "[4/6] Checking for NAS IP exposure in documentation..."
IP_EXPOSURE=$(grep -r "192\.168\." . --include="*.md" --include="*.py" --exclude-dir=node_modules --exclude-dir=.git 2>/dev/null | grep -v "example\|placeholder\|<YOUR\|TEMPLATE" | wc -l || echo 0)
if [ $IP_EXPOSURE -gt 0 ]; then
  echo -e "${YELLOW}⚠️  Found $IP_EXPOSURE references to 192.168.x.x (should use placeholders)${NC}"
  grep -r "192\.168\." . --include="*.md" --exclude-dir=node_modules --exclude-dir=.git 2>/dev/null | grep -v "example\|placeholder\|<YOUR" | head -5
  # This is a warning, not a hard fail (many docs intentionally document the real setup)
else
  echo -e "${GREEN}✓ No NAS IP exposure in public documentation${NC}"
fi

# 5. Check for uncommitted secrets in working directory
echo ""
echo "[5/6] Checking for uncommitted secrets in working directory..."
WORKING_FAIL=0
if [ -f .env ] && git diff --cached --name-only 2>/dev/null | grep -q '\.env'; then
  echo -e "${RED}❌ FAIL: .env is staged for commit!${NC}"
  WORKING_FAIL=$((WORKING_FAIL + 1))
fi
if [ -f credentials.yaml ] && git diff --cached --name-only 2>/dev/null | grep -q 'credentials'; then
  echo -e "${RED}❌ FAIL: credentials.yaml is staged for commit!${NC}"
  WORKING_FAIL=$((WORKING_FAIL + 1))
fi
if [ $WORKING_FAIL -eq 0 ]; then
  echo -e "${GREEN}✓ No secrets staged for commit${NC}"
else
  FAILED=$((FAILED + 1))
fi

# 6. Verify key infrastructure files exist
echo ""
echo "[6/6] Verifying infrastructure and config files..."
CONFIG_FAIL=0
if [ ! -f .gitleaks.toml ]; then
  echo -e "${YELLOW}⚠️  Missing .gitleaks.toml (for CI/CD secret scanning)${NC}"
fi
if [ ! -f .gitignore ]; then
  echo -e "${RED}❌ Missing .gitignore!${NC}"
  CONFIG_FAIL=$((CONFIG_FAIL + 1))
fi
if [ ! -f docker-compose.public.yml ]; then
  echo -e "${YELLOW}⚠️  Missing docker-compose.public.yml${NC}"
fi
if [ ! -f docker-compose.internal.yml ]; then
  echo -e "${YELLOW}⚠️  Missing docker-compose.internal.yml${NC}"
fi
if [ $CONFIG_FAIL -eq 0 ]; then
  echo -e "${GREEN}✓ Infrastructure files present${NC}"
else
  FAILED=$((FAILED + 1))
fi

# Summary
echo ""
echo "=========================================="
if [ $FAILED -eq 0 ]; then
  echo -e "${GREEN}✅ All checks passed! Safe for public push.${NC}"
  echo ""
  echo "Next steps:"
  echo "  1. Final manual review: git log --oneline -10"
  echo "  2. Verify staged files: git status"
  echo "  3. Push to public repo: git push origin main --tags"
  echo ""
  exit 0
else
  echo -e "${RED}❌ $FAILED check(s) failed. Do not push to public repo.${NC}"
  echo ""
  echo "Remediation steps:"
  echo "  1. Review findings above"
  echo "  2. If history contains secrets: git filter-repo --path <file>"
  echo "  3. Rotate all exposed credentials immediately"
  echo "  4. Re-run this script to verify"
  echo ""
  exit 1
fi
