#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# RVG Gateway — One-Command Setup & Run
# ══════════════════════════════════════════════════════════════════════════════
# Usage:  bash setup.sh
#
# What it does:
#   1. Checks Python 3.11+ is installed
#   2. Installs Python dependencies (requirements.txt)
#   3. Starts the RVG panel in the background (survives terminal close)
#   4. Prints the URL + default password
#
# Works on: Linux, macOS, WSL2
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Config
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${RVG_PORT:-3000}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-123456}"
LOG_FILE="${RVG_LOG_FILE:-$SCRIPT_DIR/rvg.log}"
PID_FILE="$SCRIPT_DIR/rvg.pid"

print() { echo -e "${2:-$NC}$1${NC}"; }
ok()   { print "✅ $1" "$GREEN"; }
err()  { print "❌ $1" "$RED"; }
info() { print "ℹ️  $1" "$BLUE"; }
warn() { print "⚠️  $1" "$YELLOW"; }
head() { print ""; print "═══ $1 ═══" "$CYAN"; }

# ── Step 1: Check Python ──────────────────────────────────────────────────────
head "Step 1/4: Checking Python"

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PY_VERSION="$($cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0")"
        PY_MAJOR="${PY_VERSION%%.*}"
        PY_MINOR="${PY_VERSION#*.}"
        if [ "$PY_MAJOR" -ge 3 ] 2>/dev/null && [ "$PY_MINOR" -ge 8 ] 2>/dev/null; then
            PYTHON="$cmd"
            ok "Found $cmd $PY_VERSION"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    err "Python 3.8+ not found. Install it first:"
    echo "  Ubuntu/Debian:  sudo apt install python3 python3-pip"
    echo "  macOS:          brew install python"
    echo "  CentOS/RHEL:    sudo yum install python3"
    exit 1
fi

# ── Step 2: Install dependencies ─────────────────────────────────────────────
head "Step 2/4: Installing dependencies"

cd "$SCRIPT_DIR"

if [ ! -f "requirements.txt" ]; then
    err "requirements.txt not found in $SCRIPT_DIR"
    exit 1
fi

info "Installing Python packages (this may take a minute)..."
if $PYTHON -m pip install --user -r requirements.txt --quiet 2>&1 | tail -5; then
    ok "Dependencies installed"
else
    # Try with --break-system-packages for newer pip (PEP 668)
    warn "Standard install failed, trying with --break-system-packages..."
    if $PYTHON -m pip install --user --break-system-packages -r requirements.txt --quiet 2>&1 | tail -5; then
        ok "Dependencies installed"
    else
        err "Failed to install dependencies. Try manually:"
        echo "  $PYTHON -m pip install -r requirements.txt"
        exit 1
    fi
fi

# ── Step 3: Check if already running ─────────────────────────────────────────
head "Step 3/4: Starting RVG Gateway"

if [ -f "$PID_FILE" ]; then
    OLD_PID="$(cat "$PID_FILE" 2>/dev/null || echo '')"
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        warn "RVG is already running (PID $OLD_PID). Stopping it first..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 2
        kill -9 "$OLD_PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

# Also kill anything on our port
if command -v lsof &>/dev/null; then
    OLD_PORT_PID="$(lsof -ti :$PORT 2>/dev/null || true)"
    if [ -n "$OLD_PORT_PID" ]; then
        warn "Port $PORT is in use (PID $OLD_PORT_PID). Killing..."
        kill "$OLD_PORT_PID" 2>/dev/null || true
        sleep 1
        kill -9 "$OLD_PORT_PID" 2>/dev/null || true
    fi
fi

# Start the panel using daemon.py (handles double-fork for background survival)
info "Starting RVG on port $PORT..."
RVG_PORT="$PORT" RVG_LOG_FILE="$LOG_FILE" $PYTHON daemon.py
sleep 3

# Find the actual process (daemon.py double-forks, so we need to find the child)
RVG_PID=""
for i in 1 2 3 4 5; do
    RVG_PID=""
    if command -v lsof &>/dev/null; then
        RVG_PID="$(lsof -ti :$PORT 2>/dev/null | head -1 || true)"
    fi
    if [ -z "$RVG_PID" ] && command -v ss &>/dev/null; then
        RVG_PID="$(ss -tlnp 2>/dev/null | grep ":$PORT" | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2 || true)"
    fi
    if [ -n "$RVG_PID" ]; then
        break
    fi
    sleep 1
done

if [ -z "$RVG_PID" ]; then
    err "Failed to start RVG. Check log: $LOG_FILE"
    echo ""
    echo "Last 20 log lines:"
    tail -20 "$LOG_FILE" 2>/dev/null || echo "(no log file)"
    exit 1
fi

echo "$RVG_PID" > "$PID_FILE"
ok "RVG started (PID $RVG_PID)"

# ── Step 4: Verify and print info ─────────────────────────────────────────────
head "Step 4/4: Verifying"

sleep 2

# Try to connect
if curl -s --max-time 5 -o /dev/null -w "%{http_code}" "http://localhost:$PORT/login" 2>/dev/null | grep -q "200"; then
    ok "RVG is responding on port $PORT"
else
    warn "RVG started but not responding yet. Check log: $LOG_FILE"
fi

# ── Print summary ─────────────────────────────────────────────────────────────
head "🎉 RVG Gateway is ready!"

# Detect public IP for display
PUBLIC_IP="$(curl -s --max-time 3 https://api.ipify.org 2>/dev/null || echo 'YOUR_SERVER_IP')"

cat << EOF

${CYAN}═══════════════════════════════════════════════════════════════════════════${NC}
  ${GREEN}RVG Gateway — Multi-Protocol Proxy Panel${NC}
${CYAN}═══════════════════════════════════════════════════════════════════════════${NC}

  ${BLUE}Local URL:${NC}     http://localhost:${PORT}
  ${BLUE}LAN URL:${NC}        http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'LOCAL_IP'):${PORT}
  ${BLUE}Public URL:${NC}    http://${PUBLIC_IP}:${PORT}

  ${BLUE}Admin Password:${NC} ${YELLOW}${ADMIN_PASSWORD}${NC}
  ${BLUE}Log file:${NC}       ${LOG_FILE}
  ${BLUE}PID file:${NC}        ${PID_FILE}

  ${BLUE}Working protocols:${NC}
    ✅ vless-ws       (recommended)
    ✅ trojan-ws
    ✅ shadowsocks

  ${BLUE}Commands:${NC}
    Stop:    kill \$(cat ${PID_FILE})
    Restart: bash setup.sh
    Logs:    tail -f ${LOG_FILE}

${CYAN}═══════════════════════════════════════════════════════════════════════════${NC}

EOF

print "Open ${GREEN}http://localhost:${PORT}${NC} in your browser to access the panel." ""
print "Default password: ${YELLOW}${ADMIN_PASSWORD}${NC} (change it after first login)" ""

