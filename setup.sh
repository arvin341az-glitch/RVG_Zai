#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# RVG Gateway — One-Command Setup
# ══════════════════════════════════════════════════════════════════════════════
# Run: bash setup.sh
# Does EVERYTHING. After it, Publish works.
#
# این نسخه علاوه بر نصب پایه:
#   ✅ ذخیره‌سازی ماندگار (DATA_DIR هوشمند در main.py — دیگر دیتا پاک نمی‌شود)
#   ✅ Redis محلی همراه ریپو (redis-bin/ → RVG/bin) با AOF ماندگار
#      (اگر REDIS_URL بیرونی ست شده باشد از همان استفاده می‌شود)
#   ✅ Keep-alive: run-panel.sh (مانیتور) + دیمن double-fork + watchdog.sh
#   ✅ اتصال اسکریپت dev پلتفرم به پنل → با هر بیدار شدن سندباکس، پنل خودکار بالا می‌آید
#   ✅ بکاپ چرخشی خودکار از داده‌ها (RVG/backups) + اسکریپت بازگردانی
# ══════════════════════════════════════════════════════════════════════════════

set -uo pipefail

G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; C='\033[0;36m'; N='\033[0m'
ok()   { echo -e "${G}✅ $1${N}"; }
err()  { echo -e "${R}❌ $1${N}"; }
info() { echo -e "${C}ℹ️  $1${N}"; }
warn() { echo -e "${Y}⚠️  $1${N}"; }

S="$(cd "$(dirname "$0")" && pwd)"
RVG_PORT="${RVG_PORT:-3000}"
export RVG_PORT

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
for f in daemon.py main.py central.py pages.py updater.py botgeneratedomin.py bottokentcpproxy.py zeussocks5.py requirements.txt run-panel.sh watchdog.sh restore-backup.sh; do
    [ -f "$S/$f" ] && cp "$S/$f" "$R/"
done
[ -d "$S/protocol" ] && cp -r "$S/protocol" "$R/"
# Redis همراه ریپو → RVG/bin (daemon.py خودش پیدایش می‌کند و با AOF بالا می‌آورد)
if [ -d "$S/redis-bin" ]; then
    mkdir -p "$R/bin"
    cp "$S/redis-bin/redis-server" "$R/bin/" 2>/dev/null && chmod +x "$R/bin/redis-server"
    cp "$S/redis-bin/redis-cli"    "$R/bin/" 2>/dev/null && chmod +x "$R/bin/redis-cli"
    ok "Bundled Redis → $R/bin/"
fi
# پکیج‌های python خالص همراه ریپو (کلاینت redis) → RVG/vendor
# در production بدون pip/اینترنت هم کار می‌کند.
if [ -d "$S/vendor" ]; then
    mkdir -p "$R/vendor"
    cp -r "$S/vendor/." "$R/vendor/" 2>/dev/null
    ok "Vendored redis client → $R/vendor"
fi
find "$R" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
chmod +x "$R/run-panel.sh" "$R/watchdog.sh" "$R/restore-backup.sh" 2>/dev/null || true
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

# ── 7. Wire platform dev script → panel supervisor (keep-alive on wake) ──────
info "Wiring package.json dev → RVG supervisor..."
if command -v node >/dev/null 2>&1; then
    [ -f "$P/package.json" ] && [ ! -f "$P/package.json.backup" ] && cp "$P/package.json" "$P/package.json.backup"
    node -e '
const fs = require("fs");
const f = process.argv[1];
const p = JSON.parse(fs.readFileSync(f, "utf8"));
const want = "bash RVG/run-panel.sh 2>&1 | tee dev.log";
if (p.scripts && p.scripts.dev !== want) {
  p.scripts.dev = want;
  fs.writeFileSync(f, JSON.stringify(p, null, 2) + "\n");
  console.log("dev script updated");
} else {
  console.log("dev script already wired");
}
' "$P/package.json" && ok "dev script → RVG supervisor"
else
    warn "node not found — dev script not wired (panel still runs via run-panel.sh)"
fi

# ── 8. Install Python deps ────────────────────────────────────────────────────
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

# ── 9. Free port (lsof or ss — whichever exists) ──────────────────────────────
info "Freeing port $RVG_PORT (if occupied)..."
OLD=""
if command -v lsof &>/dev/null; then
    OLD="$(lsof -ti :"$RVG_PORT" 2>/dev/null || true)"
elif command -v ss &>/dev/null; then
    OLD="$(ss -tlnp 2>/dev/null | grep ":$RVG_PORT" | grep -oP 'pid=\K[0-9]+' | sort -u | tr '\n' ' ')"
fi
if [ -n "$OLD" ]; then
    warn "Killing old process(es) on :$RVG_PORT → $OLD"
    kill $OLD 2>/dev/null || true; sleep 2
    kill -9 $OLD 2>/dev/null || true
fi

# ── 10. Stop stale monitors/daemons, start fresh via supervisor ──────────────
# فقط روی پورت استاندارد (3000) فرآیندهای کهنه را سراسری پاک می‌کنیم؛
# با پورت سفارشی، فقط همان پورت آزاد می‌شود تا به نصب‌های دیگر دست نزنیم.
if [ "$RVG_PORT" = "3000" ]; then
    pkill -f "RVG/run-panel.sh" 2>/dev/null || true
    pkill -f "python3 daemon.py" 2>/dev/null || true
    sleep 1
fi
info "Starting RVG panel (double-fork daemon + monitor + watchdog)..."
# مانیتور: دیمن را در حالت double-fork بالا می‌آورد (فرزند init → در برابر پاک‌سازی مقاوم)
# و اگر پنل مرد ظرف ~۳۰ ثانیه دوباره بالا می‌آورد. DATA_DIR داخل خود اسکریپت ست می‌شود.
if command -v setsid >/dev/null 2>&1; then
    setsid nohup bash "$R/run-panel.sh" > /dev/null 2>&1 &
else
    nohup bash "$R/run-panel.sh" > /dev/null 2>&1 &
fi
sleep 6

# ── 11. Verify ────────────────────────────────────────────────────────────────
HC=""
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    HC="$(curl -s --max-time 2 "http://localhost:$RVG_PORT/health" 2>/dev/null || true)"
    echo "$HC" | grep -q '"status"' && break
    sleep 2
done
if echo "$HC" | grep -q '"status"'; then
    ok "RVG running on port $RVG_PORT → $HC"
else
    warn "Still starting. Check: curl http://localhost:$RVG_PORT/health | log: $R/rvg.log | $R/launcher.log"
fi

if [ "$RVG_PORT" = "3000" ] && curl -s --max-time 5 -o /dev/null -w "%{http_code}" "http://localhost:81/login" 2>/dev/null | grep -q "200"; then
    ok "Gateway → :3000 working (preview panel ready)"
fi

echo ""
echo -e "${C}═══════════════════════════════════════════════════════════════${N}"
echo -e "${G}  🎉 Done! Click Publish — it will work.${N}"
echo -e "${C}═══════════════════════════════════════════════════════════════${N}"
echo ""
echo "  Preview:  via Preview Panel (right side)"
echo "  Local:    http://localhost:$RVG_PORT"
echo "  Password: 123456"
echo "  Log:      $R/rvg.log   |   launcher: $R/launcher.log   |   redis: $R/redis.log"
echo "  Data:     $R/data (ماندگار)  |  بکاپ‌ها: $R/backups  |  بازگردانی: bash RVG/restore-backup.sh"
echo ""
echo "  Architecture:"
echo "    DEV:  platform dev service → run-panel.sh (monitor) → daemon.py (double-fork) + redis (AOF)"
echo "    PROD: instrumentation.ts → daemon.py --serve + redis, Caddy :81 → :3001 (fallback :3000)"
echo "    Wake-up: sandbox idle → platform restarts dev service → panel auto-boots with data intact"
echo "    Custom port: RVG_PORT=3010 bash setup.sh  (default 3000)"
echo ""
