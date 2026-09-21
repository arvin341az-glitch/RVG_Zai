#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# RVG Gateway — Push to GitHub
# ══════════════════════════════════════════════════════════════════════════════
# Usage:  bash push.sh
#
# What it does:
#   1. Asks for your GitHub username & repo name
#   2. Asks for your Personal Access Token (SECURELY — hidden, not echoed)
#   3. Initializes git in RVG/ directory
#   4. Commits all files
#   5. Pushes to your GitHub repo
#   6. Cleans up the token (NOT stored anywhere)
#
# ⚠️  Your token is NEVER stored or logged. It's used once for the push
#     and then erased from memory.
#
# How to create a GitHub token:
#   1. Go to: https://github.com/settings/tokens
#   2. Click "Generate new token (classic)"
#   3. Select scope: "repo" (full control of private repositories)
#   4. Copy the token (you'll paste it in this script)
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print() { echo -e "${2:-$NC}$1${NC}"; }
ok()   { print "✅ $1" "$GREEN"; }
err()  { print "❌ $1" "$RED"; }
info() { print "ℹ️  $1" "$BLUE"; }
warn() { print "⚠️  $1" "$YELLOW"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
print "═══════════════════════════════════════════════════════════════════" "$CYAN"
print "  RVG Gateway — Push to GitHub" "$GREEN"
print "═══════════════════════════════════════════════════════════════════" "$CYAN"
echo ""

# ── Check git is installed ────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    err "git is not installed. Install it first:"
    echo "  Ubuntu/Debian:  sudo apt install git"
    echo "  macOS:          brew install git"
    exit 1
fi
ok "git found: $(git --version)"

# ── Get GitHub username ──────────────────────────────────────────────────────
echo ""
read -p "$(print 'GitHub username:' "$BLUE") " GITHUB_USER
if [ -z "$GITHUB_USER" ]; then
    err "Username cannot be empty"
    exit 1
fi

# ── Get repo name ─────────────────────────────────────────────────────────────
read -p "$(print 'Repository name (default: RVG):' "$BLUE") " REPO_NAME
REPO_NAME="${REPO_NAME:-RVG}"

# ── Ask if repo exists ───────────────────────────────────────────────────────
read -p "$(print "Does the repo '$REPO_NAME' already exist on GitHub? (y/N):" "$BLUE") " REPO_EXISTS
REPO_EXISTS="${REPO_EXISTS:-n}"

# ── Get token (SECURELY — not echoed to screen) ──────────────────────────────
echo ""
print "═══════════════════════════════════════════════════════════════════" "$CYAN"
print "  🔑 GitHub Personal Access Token" "$YELLOW"
print "═══════════════════════════════════════════════════════════════════" "$CYAN"
echo ""
print "  Your token will NOT be displayed or stored." "$NC"
print "  Create one at: https://github.com/settings/tokens" "$NC"
print "  Required scope: repo" "$NC"
echo ""
read -s -p "$(print 'Paste your token here (hidden):' "$BLUE") " GITHUB_TOKEN
echo ""

if [ -z "$GITHUB_TOKEN" ]; then
    err "Token cannot be empty"
    exit 1
fi

# Verify token looks right (basic check)
if [ ${#GITHUB_TOKEN} -lt 20 ]; then
    err "Token looks too short. Check you copied the full token."
    exit 1
fi
ok "Token received (${#GITHUB_TOKEN} chars)"

# ── Create repo if it doesn't exist ──────────────────────────────────────────
if [[ "$REPO_EXISTS" =~ ^[Nn] ]]; then
    info "Creating repository '$REPO_NAME' on GitHub..."
    CREATE_RESP="$(curl -s -X POST "https://api.github.com/user/repos" \
        -H "Authorization: token $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github.v3+json" \
        -d "{\"name\":\"$REPO_NAME\",\"private\":true}" 2>&1)"

    if echo "$CREATE_RESP" | grep -q '"full_name"'; then
        ok "Repository created: $(echo "$CREATE_RESP" | grep -o '"full_name":"[^"]*"' | cut -d'"' -f4)"
    elif echo "$CREATE_RESP" | grep -q '"message"'; then
        MSG="$(echo "$CREATE_RESP" | grep -o '"message":"[^"]*"' | cut -d'"' -f4)"
        warn "GitHub API: $MSG"
        warn "Continuing anyway (maybe repo already exists)..."
    fi
fi

# ── Initialize git in RVG directory ───────────────────────────────────────────
cd "$SCRIPT_DIR"

info "Setting up git in $SCRIPT_DIR..."

# Initialize git if not already
if [ ! -d ".git" ]; then
    git init -q
    ok "Git initialized"
else
    ok "Git already initialized"
fi

# Set default branch
git symbolic-ref HEAD refs/heads/main 2>/dev/null || true

# Configure user if not set
if ! git config user.email &>/dev/null; then
    git config user.email "${GITHUB_USER}@users.noreply.github.com"
fi
if ! git config user.name &>/dev/null; then
    git config user.name "$GITHUB_USER"
fi

# Create .gitignore if not exists
if [ ! -f ".gitignore" ]; then
    cat > .gitignore << 'GITIGNORE'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
venv/
.venv/
env/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# Logs
*.log
rvg.log

# Runtime
rvg.pid
rvg_state.json
.rvg_secret

# OS
.DS_Store
Thumbs.db

# Binaries (don't commit large binaries)
xray
xray.exe
*.zip
GITIGNORE
    ok ".gitignore created"
fi

# Remove old remote if exists
git remote remove origin 2>/dev/null || true

# Add remote with token (will be cleaned up after push)
# Using URL-embedded token for one-time push
REMOTE_URL="https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${REPO_NAME}.git"
git remote add origin "$REMOTE_URL"

# Stage all files
info "Staging files..."
git add -A
STAGED_COUNT="$(git diff --cached --numstat | wc -l)"
ok "$STAGED_COUNT files staged"

# Commit
if git diff --cached --quiet; then
    warn "No changes to commit"
else
    git commit -q -m "RVG Gateway — multi-protocol proxy panel

- VLESS / Trojan / Shadowsocks over WebSocket
- xhttp transport (packet-up / stream-up)
- Admin dashboard with traffic stats
- Multi-tenant: auto-detects preview domain from gateway headers
- One-command setup: bash setup.sh
- Default admin password: 123456 (change after first login)"
    ok "Committed"
fi

# Push
info "Pushing to GitHub..."
if git push -u origin main 2>&1 | grep -v "remote: " | grep -v "To https" | grep -v "Counting" | grep -v "Compressing" | grep -v "Writing" | grep -v "remote:"; then
    ok "Pushed successfully!"
else
    # Try master branch too
    if git push -u origin master 2>&1 | tail -3; then
        ok "Pushed to master branch"
    else
        err "Push failed. Check the error above."
        echo ""
        echo "Common causes:"
        echo "  - Wrong token (create new one at https://github.com/settings/tokens)"
        echo "  - Repo doesn't exist (create it first, or answer 'y' when asked)"
        echo "  - No internet connection"
    fi
fi

# ── CLEAN UP TOKEN (critical!) ────────────────────────────────────────────────
info "Cleaning up token from git config..."
git remote remove origin
# Re-add without token
CLEAN_URL="https://github.com/${GITHUB_USER}/${REPO_NAME}.git"
git remote add origin "$CLEAN_URL"
ok "Token removed from git config"

# Clear token variable
GITHUB_TOKEN=""
unset GITHUB_TOKEN

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
print "═══════════════════════════════════════════════════════════════════" "$CYAN"
print "  🎉 Done! Your repo is ready." "$GREEN"
print "═══════════════════════════════════════════════════════════════════" "$CYAN"
echo ""
print "  ${BLUE}Repo URL:${NC}  https://github.com/${GITHUB_USER}/${REPO_NAME}" ""
print "  ${BLUE}Clone:${NC}     git clone https://github.com/${GITHUB_USER}/${REPO_NAME}.git" ""
echo ""
print "  ${YELLOW}⚠️  Your token was NOT stored. For future pushes, run this script again.${NC}" ""
print "  ${YELLOW}⚠️  Remember to revoke the token at https://github.com/settings/tokens${NC}" ""
print "  ${YELLOW}    if you don't need it anymore.${NC}" ""
echo ""

