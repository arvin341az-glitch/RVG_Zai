# RVG Gateway — One-Command Setup

Clone and run the RVG Gateway proxy panel with a single command.

## Quick Start (paste this to any AI assistant)

```
Clone the repository https://github.com/ggabhdnfj/RVG_chatZ.git and run the RVG Gateway proxy panel.

Steps:
1. Clone: git clone https://github.com/ggabhdnfj/RVG_chatZ.git
2. Enter directory: cd RVG_chatZ
3. Run the one-command setup script: bash setup.sh

That's it. The setup.sh script will:
- Check Python 3.8+ is installed
- Install Python dependencies from requirements.txt
- Start the RVG panel in the background (survives terminal close)
- Print the URL and default admin password (123456)

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
