#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# RVG Gateway — One-Command Setup
# ══════════════════════════════════════════════════════════════════════════════
# This script does EVERYTHING:
#   1. Finds the Next.js project root
#   2. Copies Python app files to <project>/RVG/
#   3. Installs integration files (instrumentation.ts, Caddyfile, page.tsx)
#   4. Installs Python dependencies
#   5. Starts the panel on port 3000 (the only port visible to users)
#   6. Verifies it's running
#
# After running this, click "Publish" — it will work because all integration
# files are in place.
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✅ $1${NC}"; }
err()  { echo -e "${RED}❌ $1${NC}"; }
info() { echo -e "${CYAN}ℹ️  $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  RVG Gateway — One-Command Setup${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# ── Step 1: Find Next.js project root ─────────────────────────────────────────
info "Step 1/6: Finding Next.js project root..."

PROJECT_DIR=""
# Look in parent directories for package.json with next dependency
CHECK_DIR="$SCRIPT_DIR"
for i in 1 2 3 4 5; do
    if [ -f "$CHECK_DIR/package.json" ] && grep -q '"next"' "$CHECK_DIR/package.json" 2>/dev/null; then
        PROJECT_DIR="$CHECK_DIR"
        break
    fi
    CHECK_DIR="$(dirname "$CHECK_DIR")"
    [ "$CHECK_DIR" = "/" ] && break
done

# Also check if we're inside a directory that has src/app (Next.js App Router)
if [ -z "$PROJECT_DIR" ]; then
    CHECK_DIR="$SCRIPT_DIR"
    for i in 1 2 3 4 5; do
        if [ -d "$CHECK_DIR/src/app" ]; then
            PROJECT_DIR="$CHECK_DIR"
            break
        fi
        CHECK_DIR="$(dirname "$CHECK_DIR")"
        [ "$CHECK_DIR" = "/" ] && break
    done
fi

if [ -z "$PROJECT_DIR" ]; then
    err "Next.js project not found."
    echo ""
    echo "This script must be run inside a Next.js project."
    echo "Clone this repo INTO the Next.js project directory, then run:"
    echo "  bash RVG_chatZ/setup.sh"
    exit 1
fi

ok "Found Next.js project: $PROJECT_DIR"

# ── Step 2: Copy Python app to <project>/RVG/ ────────────────────────────────
info "Step 2/6: Copying Python app files..."

RVG_DIR="$PROJECT_DIR/RVG"
mkdir -p "$RVG_DIR"

# Copy all Python files and protocol directory
for item in daemon.py main.py central.py pages.py updater.py \
            botgeneratedomin.py bottokentcpproxy.py zeussocks5.py \
            protocol requirements.txt; do
    if [ -e "$SCRIPT_DIR/$item" ]; then
        cp -r "$SCRIPT_DIR/$item" "$RVG_DIR/"
    fi
done

# Clean __pycache__
find "$RVG_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

ok "Python app copied to $RVG_DIR"

# ── Step 3: Install integration files ─────────────────────────────────────────
info "Step 3/6: Installing integration files..."

# requirements.txt at project root (for build pipeline)
cp "$SCRIPT_DIR/requirements.txt" "$PROJECT_DIR/requirements.txt"
ok "requirements.txt → project root"

# instrumentation.ts → src/
mkdir -p "$PROJECT_DIR/src"
cp "$SCRIPT_DIR/integration/instrumentation.ts" "$PROJECT_DIR/src/instrumentation.ts"
ok "instrumentation.ts → src/"

# Caddyfile → project root (backup original if exists)
if [ -f "$PROJECT_DIR/Caddyfile" ] && [ ! -f "$PROJECT_DIR/Caddyfile.backup" ]; then
    cp "$PROJECT_DIR/Caddyfile" "$PROJECT_DIR/Caddyfile.backup"
    warn "Original Caddyfile backed up to Caddyfile.backup"
fi
cp "$SCRIPT_DIR/integration/Caddyfile" "$PROJECT_DIR/Caddyfile"
ok "Caddyfile → project root (proxies to port 3001)"

# page.tsx → src/app/ (backup original if exists)
mkdir -p "$PROJECT_DIR/src/app"
if [ -f "$PROJECT_DIR/src/app/page.tsx" ] && [ ! -f "$PROJECT_DIR/src/app/page.backup.tsx" ]; then
    cp "$PROJECT_DIR/src/app/page.tsx" "$PROJECT_DIR/src/app/page.backup.tsx"
    warn "Original page.tsx backed up to page.backup.tsx"
fi
cp "$SCRIPT_DIR/integration/page.tsx" "$PROJECT_DIR/src/app/page.tsx"
ok "page.tsx → src/app/"

# ── Step 4: Install Python dependencies ──────────────────────────────────────
info "Step 4/6: Installing Python dependencies..."

cd "$RVG_DIR"

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    err "Python 3 not found. Install: sudo apt install python3 python3-pip"
    exit 1
fi

ok "Python: $($PYTHON --version 2>&1)"

if $PYTHON -m pip install -r requirements.txt --quiet 2>&1 | tail -3; then
    ok "Dependencies installed"
else
    warn "Trying with --break-system-packages..."
    $PYTHON -m pip install --break-system-packages -r requirements.txt --quiet 2>&1 | tail -3
    ok "Dependencies installed"
fi

# ── Step 5: Start the panel ───────────────────────────────────────────────────
info "Step 5/6: Starting RVG panel on port 3000..."

# Kill anything on port 3000 (Next.js dev server)
if command -v lsof &>/dev/null; then
    OLD_PID="$(lsof -ti :3000 2>/dev/null || true)"
    if [ -n "$OLD_PID" ]; then
        warn "Killing process on port 3000 (PID $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 2
        kill -9 "$OLD_PID" 2>/dev/null || true
    fi
fi

# Start Python app via daemon.py (double-fork to survive terminal close)
RVG_PORT=3000 RVG_LOG_FILE="$RVG_DIR/rvg.log" $PYTHON daemon.py
sleep 4

# Verify
if curl -s --max-time 5 -o /dev/null -w "%{http_code}" "http://localhost:3000/health" 2>/dev/null | grep -q "200"; then
    ok "RVG panel is running on port 3000"
else
    warn "Panel may still be starting. Check: curl http://localhost:3000/health"
    echo "  Log: $RVG_DIR/rvg.log"
fi

# ── Step 6: Summary ───────────────────────────────────────────────────────────
info "Step 6/6: Done!"

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  🎉 RVG Gateway is ready!${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Panel URL:     http://localhost:3000"
echo "  Admin password: 123456"
echo "  Log file:      $RVG_DIR/rvg.log"
echo ""
echo -e "  ${YELLOW}Publish:${NC} Click the Publish button — it will work."
echo -e "  ${YELLOW}Protocols:${NC} vless-ws, trojan-ws, shadowsocks (recommended)"
echo ""
echo -e "  ${CYAN}To stop:${NC} kill \$(lsof -ti :3000)"
echo -e "  ${CYAN}To restart:${NC} bash $SCRIPT_DIR/setup.sh"
echo ""
