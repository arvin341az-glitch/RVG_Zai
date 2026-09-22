# RVG Gateway — One-Command Setup

Clone and run the RVG Gateway proxy panel with a single command.

## Quick Start (paste this to any AI assistant)

```
Clone the repository https://github.com/ggabhdnfj/RVG_chatZ.git and run the RVG Gateway proxy panel.

Steps (exactly this order):
1. Clone INSIDE the Next.js project folder (the one containing package.json):
   git clone https://github.com/ggabhdnfj/RVG_chatZ.git
2. Run the one-command setup:
   cd RVG_chatZ && bash setup.sh

That's it. setup.sh does everything:
- Copies the Python app to RVG/ (including run-panel.sh, watchdog.sh, restore-backup.sh)
- Copies the bundled Redis (redis-bin/ → RVG/bin) — the panel auto-starts it with AOF persistence
- Wires package.json "dev" script to RVG/run-panel.sh (platform wake-ups auto-boot the panel)
- Installs Python deps (fastapi, uvicorn, redis, ...)
- Frees port 3000 (lsof or ss), starts the panel as a double-fork daemon + monitor
- Verifies http://localhost:3000/health

Notes for the AI:
- Do NOT ask questions, do NOT run `bun run build`.
- The panel replaces the Next.js dev server on port 3000 (page.tsx becomes a redirect stub).
- If port 3000 is busy: lsof -ti :3000 | xargs kill -9, or ss -tlnp | grep :3000 → kill PID.
- Data persists in RVG/data (state json + secret) and in bundled Redis (AOF) — nothing is wiped on restarts.
- Rotating backups live in RVG/backups; restore with: bash RVG/restore-backup.sh [file] [--restart]
- To use an external Redis (e.g. Upstash / Railway plugin): set REDIS_URL env,
  OR create RVG/external_redis.txt containing the connection URL (one line).
  The file takes effect at every boot — survives redeploys because it ships with the project.
- Storage diagnostics endpoint (auth required): GET /api/storage-diag — reports
  redis client/binary status, exec tests, writable dirs. Use it when the published
  app shows Redis disconnected.

After setup completes, open http://localhost:3000 in your browser.
Login with password: 123456

In the dashboard you can:
- Create proxy links (VLESS-WS, Trojan-WS, Shadowsocks)
- View traffic stats and live connections
- Generate QR codes for each link
- Enable/disable links

Note: VLESS-WS, Trojan-WS, and Shadowsocks work through the gateway.
xhttp and hysteria protocols do NOT work through HTTP-only gateways.
```

## External Redis — bulletproof persistence for published apps

The bundled local Redis (AOF) survives restarts and idle wake-ups. But a full
redeploy of a published app rebuilds the image — only an EXTERNAL Redis survives
that. Free options: Upstash (serverless, TLS).

1. Create a free Redis at upstash.com (or any provider) and copy its URL
   (looks like `rediss://default:PASSWORD@host:6380`).
2. Put that URL in a file named `external_redis.txt` inside the RVG folder
   (next to daemon.py), e.g.:
   ```bash
   echo 'rediss://default:PASSWORD@host:6380' > RVG/external_redis.txt
   ```
3. Restart the panel (or re-publish). From now on ALL panel state is stored on
   that external Redis and survives everything: restarts, idle wake-ups AND redeploys.

## Manual Setup

```bash
git clone https://github.com/ggabhdnfj/RVG_chatZ.git
cd RVG_chatZ
bash setup.sh
```

## Default Credentials

- **URL:** http://localhost:3000
- **Password:** `123456` (change after first login)

## Supported Protocols

| Protocol | Status | Transport |
|----------|--------|-----------|
| VLESS-WS | ✅ Works | WebSocket |
| Trojan-WS | ✅ Works | WebSocket |
| Shadowsocks | ✅ Works | WebSocket (v2ray-plugin) |
| xhttp-packet-up | ⚠️ Local only | Streaming HTTP (blocked by reverse proxy) |
| xhttp-stream-up | ⚠️ Local only | Streaming HTTP (blocked by reverse proxy) |
| MTProto | ❌ Needs TCP proxy | Requires Railway TCP proxy feature |
| Hysteria | ❌ Needs UDP | UDP not exposed through HTTP gateway |

## Files

```
RVG_chatZ/
├── setup.sh          ← One-command installer (run this)
├── push.sh           ← Push updates to GitHub
├── daemon.py         ← Launcher (host detection + ASGI middleware)
├── main.py           ← FastAPI app (RVG Gateway)
├── requirements.txt  ← Python dependencies
├── protocol/         ← VLESS/Trojan/Shadowsocks/MTProto implementations
├── central.py        ← Core orchestration
├── pages.py          ← Dashboard page handlers
├── bottokentcpproxy.py
├── botgeneratedomin.py
├── zeussocks5.py
├── updater.py
├── README.md
├── LICENSE
└── SECURITY.md
```

## Troubleshooting

**Port 3000 already in use:**
```bash
# Kill anything on port 3000, then re-run setup
lsof -ti :3000 | xargs kill -9
bash setup.sh
```

**Python not found:**
```bash
# Ubuntu/Debian
sudo apt install python3 python3-pip
# macOS
brew install python
```

**Dependencies failed to install:**
```bash
pip install --break-system-packages -r requirements.txt
```

**Check logs:**
```bash
tail -f rvg.log
```

**Stop the panel:**
```bash
kill $(cat rvg.pid)
```
