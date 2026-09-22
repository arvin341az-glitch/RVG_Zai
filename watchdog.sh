#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# RVG Watchdog — last-resort auto-recovery
# ══════════════════════════════════════════════════════════════════════════════
# Every 20s: if /health is down AND no run-panel.sh supervisor is alive,
# spawn one (detached). Singleton via flock. If the platform's own dev service
# manages the panel, the watchdog simply does nothing.
# ══════════════════════════════════════════════════════════════════════════════

RVG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK="$RVG_DIR/.watchdog.lock"
WLOG="$RVG_DIR/watchdog.log"

exec 8>"$LOCK"
flock -n 8 || exit 0

echo "[rvg-watchdog] started $(date '+%F %T')" >> "$WLOG"

while true; do
    sleep 20
    if curl -s --max-time 3 http://localhost:3000/health | grep -q '"status"'; then
        continue
    fi
    if pgrep -f "run-panel.sh" > /dev/null 2>&1; then
        continue   # supervisor alive — it is (re)starting the gateway itself
    fi
    echo "[rvg-watchdog] panel down, no supervisor — booting one $(date '+%F %T')" >> "$WLOG"
    setsid nohup bash "$RVG_DIR/run-panel.sh" >> "$WLOG" 2>&1 &
done
