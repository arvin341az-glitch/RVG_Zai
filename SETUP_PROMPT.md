# RVG Gateway — One-Command Setup

Clone and run the RVG Gateway proxy panel with a single command.

## Quick Start (paste this to any AI assistant)

```
سلام. تو دستیار فنی هستی و مأموریت تو نصب و راه‌اندازی «پنل RVG Gateway v9.2» روی این محیط است.

ریپو: https://github.com/ggabhdnfj/RVG_chatZ.git

دقیقاً مراحل زیر را به همین ترتیب انجام بده. هیچ سوالی نپرس و هیچ فایلی از ریپو را ویرایش یا حذف نکن.

مرحله ۱ — دانلود پروژه:
git clone https://github.com/ggabhdnfj/RVG_chatZ.git
cd RVG_chatZ
(اگر داخل یک پروژه Next.js هستی، ریپو را داخل همان پوشه‌ای کلون کن که package.json دارد.)

مرحله ۲ — نصب، فقط با یک دستور:
bash setup.sh
- پیش‌فرض پنل روی پورت 3000 بالا می‌آید. اگر پورت دیگری می‌خواهی: RVG_PORT=3010 bash setup.sh
- این اسکریپت خودش همه‌چیز را انجام می‌دهد: نصب وابستگی‌های پایتون، کپی فایل‌ها، راه‌اندازی Redis همراه (با AOF ماندگار)، مانیتور keep-alive و بکاپ‌گیری خودکار.
- نیازی به نصب دستی هیچ‌چیز نیست؛ حتی باینری Redis داخل ریپو هست و اینترنت نمی‌خواهد.
- اگر پورت اشغال باشد، خود اسکریپت آزادش می‌کند.

مرحله ۳ — صبر کن تا نصب تمام شود (حداکثر ~۲ دقیقه) و بعد سلامت را چک کن:
curl http://127.0.0.1:3000/health
خروجی درست باید {"status":"ok", ... , "panel_version":"9.2.3-embed"} باشد.
(اگر پورت دیگری گذاشتی همان پورت را چک کن.)

مرحله ۴ — ورود و بررسی نهایی:
- آدرس پنل: http://127.0.0.1:3000/login — رمز: 123456
- لاگین با API:
  curl -c /tmp/rvg.c -X POST http://127.0.0.1:3000/api/login -H "Content-Type: application/json" -d '{"password":"123456"}'
- وضعیت پنل:
  curl -b /tmp/rvg.c http://127.0.0.1:3000/stats
- فیلد redis_connected باید true و storage_backend باید redis باشد.

قوانین حین کار:
1. پوشه RVG/ — مخصوصاً RVG/data — را هرگز پاک نکن؛ همه داده‌ها و کلید نشست‌ها آنجاست.
2. setup.sh را پشت‌سرهم اجرا نکن. اگر خطا دیدی اول لاگ‌ها را بخوان: RVG/launcher.log و RVG/rvg.log
3. پنل با پایتون اجرا می‌شود (daemon.py) و نباید با bun/npm بیلد شود.
4. بعد از ری‌استارت سرور، اگر پنل بالا نیامد: bash RVG/run-panel.sh
5. بکاپ‌ها در RVG/backups هستند؛ بازیابی: bash RVG/restore-backup.sh --list و bash RVG/restore-backup.sh <file> --restart
6. عیب‌یابی کامل ذخیره‌سازی/Redis (بعد از لاگین): curl -b /tmp/rvg.c http://127.0.0.1:3000/api/storage-diag
7. ردیوس خارجی (اختیاری ولی برای محیط‌های پابلیش بهتر است): URL ردیوس را در فایل RVG/external_redis.txt بگذار؛ مثل:
   echo 'rediss://default:PASSWORD@host:6380' > RVG/external_redis.txt
   و بعد پنل را ری‌استارت کن. با این کار داده‌ها حتی بین دیپلوی‌های کامل هم می‌مانند.
8. اگر /health جواب نداد: با pgrep -af daemon.py وضعیت پروسه را چک کن و در صورت نیاز bash RVG/run-panel.sh را اجرا کن.

در پایان یک گزارش کوتاه بده: خروجی /health، مقدار redis_connected و storage_backend، تعداد کانفیگ‌ها (links_count)، آدرس پنل و رمز ورود.
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
