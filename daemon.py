"""
RVG launcher — works in both sandbox (double-fork daemon) and production
(direct serve, called from Next.js instrumentation.ts).

Key features (without modifying main.py):
  1. PublicHostRewriter ASGI middleware: the fcapp gateway rewrites Host to
     its internal hostname and preserves the real preview domain in the
     "Abc" header. This middleware rewrites X-Forwarded-Host so main.py's
     host-detection picks up the real domain → share-link generation works
     for ANY user's preview domain (multi-tenant, nothing hardcoded).
  2. TrailingSlashStripper: fixes redirect loops behind reverse proxy.
  3. Monkey-patch generate_share_link / generate_ss_link: configs match
     the access environment (localhost → 3000/no-TLS, public → 443/TLS).
  4. /xray-config/{uuid} and /clash/{uuid} endpoints: full client configs
     WITH the x-session-id header required by the fcapp gateway (share
     links can't carry custom headers).

Usage:
  python3 daemon.py          # sandbox: double-fork to PID 1
  python3 daemon.py --serve  # production: direct serve (called by instrumentation.ts)
"""
import os
import sys
import json
import time
import base64
import shutil
import socket
import tempfile
import subprocess
from urllib.parse import quote

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.environ.get("RVG_LOG_FILE", "/home/z/my-project/rvg.log")
PORT = os.environ.get("RVG_PORT", "3000")
REDIS_PORT = int(os.environ.get("RVG_REDIS_PORT", "6379"))

# ── Host detection ────────────────────────────────────────────────────────────

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
_INTERNAL_GATEWAY_MARKERS = (
    ".fcapp.run",
    ".fc.aliyuncs.com",
)


def _is_local(host: str) -> bool:
    if host in _LOCAL_HOSTS:
        return True
    if host.startswith("127."):
        return True
    if host.startswith("192.168.") or host.startswith("10."):
        return True
    return False


def _is_internal_gateway(host: str) -> bool:
    h = host.lower()
    for marker in _INTERNAL_GATEWAY_MARKERS:
        if marker in h:
            return True
    return False


def _session_id(uuid: str) -> str:
    return f"rvg-{uuid[:8]}"


# ── ASGI middleware: rewrite public host ─────────────────────────────────────

class PublicHostRewriter:
    """
    The fcapp gateway rewrites Host to its internal hostname but preserves
    the original public domain in the "Abc" header. We rewrite
    X-Forwarded-Host so main.py's _detect_public_host middleware sees the
    real preview domain. This is what makes share-link generation work for
    ANY user's preview domain (multi-tenant).
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            headers = scope.get("headers", [])
            abc_value = None
            xfh_value = None
            for k, v in headers:
                kl = k.decode("latin-1").lower()
                vv = v.decode("latin-1")
                if kl == "abc":
                    abc_value = vv
                elif kl == "x-forwarded-host":
                    xfh_value = vv.split(",")[0].strip()

            real_host = None
            if abc_value and not _is_local(abc_value):
                # The fcapp gateway's "Abc" header carries the subdomain part
                # of the preview URL. If it already contains a dot, it's a
                # full domain; otherwise it's just the subdomain and we need
                # to append the platform TLD.
                if "." in abc_value:
                    real_host = abc_value
                else:
                    # Subdomain only — append the platform TLD.
                    # This works for all Z.ai Code preview/published URLs.
                    real_host = abc_value + ".space-z.ai"
            elif xfh_value and not _is_internal_gateway(xfh_value) and not _is_local(xfh_value):
                real_host = xfh_value

            if real_host:
                new_headers = []
                for k, v in headers:
                    if k.decode("latin-1").lower() != "x-forwarded-host":
                        new_headers.append((k, v))
                new_headers.append(
                    (b"x-forwarded-host", real_host.encode("latin-1"))
                )
                scope["headers"] = new_headers

        await self.inner(scope, receive, send)


class TrailingSlashStripper:
    """Strip trailing slashes to avoid Starlette's 307 redirect (which
    drops the port behind a reverse proxy, causing infinite loops)."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path", "")
            if len(path) > 1 and path.endswith("/"):
                new_path = path.rstrip("/")
                scope["path"] = new_path
                scope["raw_path"] = new_path.encode("ascii", "ignore")
        await self.inner(scope, receive, send)


# ── Config generation patch ───────────────────────────────────────────────────

def patch_config_generation(main_mod):
    LINKS = main_mod.LINKS
    DEFAULT_PROTOCOL = main_mod.DEFAULT_PROTOCOL

    try:
        import protocol.shadowsocks.shadowsocks as ss_mod

        def generate_ss_link(host, port, cipher, password, remark):
            userinfo = base64.urlsafe_b64encode(
                f"{cipher}:{password}".encode()
            ).decode().rstrip("=")
            if _is_local(host):
                plugin = quote(f"v2ray-plugin;mux=0;path=/ss-ws;host={host}")
            else:
                plugin = quote(f"v2ray-plugin;tls;mux=0;path=/ss-ws;host={host}")
            return f"ss://{userinfo}@{host}:{port}/?plugin={plugin}#{quote(remark)}"

        ss_mod.generate_ss_link = generate_ss_link
        main_mod.generate_ss_link = generate_ss_link
    except Exception as e:
        print(f"[patch] ss link patch failed: {e}", file=sys.stderr)

    def generate_share_link(uuid, host, remark="RVG", protocol=DEFAULT_PROTOCOL):
        link = LINKS.get(uuid) or {}
        local = _is_local(host)

        if local:
            port, security = PORT, "none"
            tls_params = {}
        else:
            port, security = "443", "tls"
            # IMPORTANT: gateway (Alibaba FC) only supports HTTP/1.1, NOT HTTP/2.
            # xhttp over HTTP/2 causes "frame too large" errors → 502.
            # Force alpn=http/1.1 for all public-facing configs.
            tls_params = {"sni": host, "fp": "chrome", "alpn": "http/1.1"}

        if protocol == "mtproto":
            secret = link.get("mtproto_secret")
            if not secret:
                return f"tg://proxy?server={host}&port=0&secret=not_ready#{quote(remark)}"
            pub_host = link.get("mtproto_public_host")
            pub_port = link.get("mtproto_public_port")
            if not pub_host or not pub_port:
                return f"tg://proxy?server={host}&port=0&secret=not_ready#{quote(remark)}"
            from protocol.mtproto import mtproto_native as mtproto
            return mtproto.generate_mtproto_link(
                pub_host, pub_port, secret,
                mtproto.sanitize_domain(link.get("mtproto_domain"))
            )

        if protocol == "shadowsocks":
            cipher = link.get("ss_cipher", main_mod.DEFAULT_CIPHER)
            password = link.get("ss_password", "")
            return generate_ss_link(host, int(port), cipher, password, remark)

        def _build_params(net_type, mode, path):
            params = {
                "encryption": "none",
                "security": security,
                "type": net_type,
                "host": host,
                "path": path,
            }
            if mode:
                params["mode"] = mode
            params.update(tls_params)
            return params

        if protocol == "trojan-ws":
            params = _build_params("ws", None, "/trojan-ws")
            query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
            return f"trojan://{uuid}@{host}:{port}?{query}#{quote(remark)}"

        if protocol.startswith("trojan-xhttp-"):
            mode = protocol.replace("trojan-xhttp-", "")
            path = f"/txhttp-siz10/{mode}/{uuid}"
            params = _build_params("xhttp", mode, path)
            query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
            return f"trojan://{uuid}@{host}:{port}?{query}#{quote(remark)}"

        if protocol == "vless-ws":
            path = f"/ws/{uuid}"
            params = _build_params("ws", None, path)
        else:
            mode = protocol.replace("xhttp-", "")
            path = f"/xhttp-siz10/{mode}/{uuid}"
            params = _build_params("xhttp", mode, path)
        query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
        return f"vless://{uuid}@{host}:{port}?{query}#{quote(remark)}"

    main_mod.generate_share_link = generate_share_link


# ── Xray / Clash config generators ────────────────────────────────────────────

def _xray_outbound(uuid_val, host, protocol, link, local=False):
    sid = _session_id(uuid_val)
    if local:
        addr, port = host, int(PORT)
        tls_settings = None
    else:
        addr, port = host, 443
        tls_settings = {
            "serverName": host,
            "fingerprint": "chrome",
            "alpn": ["http/1.1"],
        }

    def _ss(network, path, mode=None):
        ss = {"network": network}
        ss["security"] = "tls" if tls_settings else "none"
        if tls_settings:
            ss["tlsSettings"] = tls_settings
        if network == "ws":
            ss["wsSettings"] = {"path": path, "headers": {"Host": host, "x-session-id": sid}}
        else:
            xhs = {"path": path, "host": host, "headers": {"x-session-id": sid}}
            if mode:
                xhs["mode"] = mode
            ss["xhttpSettings"] = xhs
        return ss

    if protocol.startswith("vless") or protocol.startswith("xhttp"):
        if protocol == "vless-ws":
            stream = _ss("ws", f"/ws/{uuid_val}")
        else:
            mode = protocol.replace("xhttp-", "")
            stream = _ss("xhttp", f"/xhttp-siz10/{mode}/{uuid_val}", mode)
        return {
            "tag": "proxy-out", "protocol": "vless",
            "settings": {"vnext": [{"address": addr, "port": port,
                "users": [{"id": uuid_val, "encryption": "none"}]}]},
            "streamSettings": stream,
        }

    if protocol.startswith("trojan"):
        if protocol == "trojan-ws":
            stream = _ss("ws", "/trojan-ws")
        else:
            mode = protocol.replace("trojan-xhttp-", "")
            stream = _ss("xhttp", f"/txhttp-siz10/{mode}/{uuid_val}", mode)
        return {
            "tag": "proxy-out", "protocol": "trojan",
            "settings": {"servers": [{"address": addr, "port": port, "password": uuid_val}]},
            "streamSettings": stream,
        }

    if protocol == "shadowsocks":
        cipher = link.get("ss_cipher", "chacha20-ietf-poly1305")
        password = link.get("ss_password", "")
        stream = _ss("ws", "/ss-ws")
        return {
            "tag": "proxy-out", "protocol": "shadowsocks",
            "settings": {"servers": [{"address": addr, "port": port,
                "method": cipher, "password": password}]},
            "streamSettings": stream,
        }
    return None


def _build_xray_config(uuid_val, host, protocol, link, local=False):
    ob = _xray_outbound(uuid_val, host, protocol, link, local)
    if not ob:
        return None
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {"tag": "socks-in", "port": 10808, "listen": "127.0.0.1",
             "protocol": "socks", "settings": {"udp": True}},
            {"tag": "http-in", "port": 10809, "listen": "127.0.0.1",
             "protocol": "http", "settings": {}},
        ],
        "outbounds": [ob],
    }


def _build_clash_config(uuid_val, host, protocol, link, local=False):
    sid = _session_id(uuid_val)
    port = int(PORT) if local else 443
    tls_en = not local
    name = f"RVG-{protocol}"
    proxy = {"name": name, "udp": True}

    if protocol.startswith("vless") or protocol.startswith("xhttp"):
        proxy["type"] = "vless"
        proxy["uuid"] = uuid_val
    elif protocol.startswith("trojan"):
        proxy["type"] = "trojan"
        proxy["password"] = uuid_val
    elif protocol == "shadowsocks":
        proxy["type"] = "ss"
        proxy["cipher"] = link.get("ss_cipher", "chacha20-ietf-poly1305")
        proxy["password"] = link.get("ss_password", "")

    proxy["server"] = host
    proxy["port"] = port
    if tls_en:
        proxy["tls"] = True
        proxy["servername"] = host

    if protocol in ("vless-ws", "trojan-ws"):
        p = f"/ws/{uuid_val}" if protocol == "vless-ws" else "/trojan-ws"
        proxy["network"] = "ws"
        proxy["ws-opts"] = {"path": p, "headers": {"Host": host, "x-session-id": sid}}
    elif protocol == "shadowsocks":
        proxy["network"] = "ws"
        proxy["ws-opts"] = {"path": "/ss-ws", "headers": {"Host": host, "x-session-id": sid}}
    elif "xhttp" in protocol:
        mode = protocol.replace("xhttp-", "").replace("trojan-xhttp-", "")
        p = f"/txhttp-siz10/{mode}/{uuid_val}" if protocol.startswith("trojan") else f"/xhttp-siz10/{mode}/{uuid_val}"
        proxy["network"] = "ws"
        proxy["ws-opts"] = {"path": p, "headers": {"Host": host, "x-session-id": sid}}

    return (
        "proxies:\n"
        f"  - {json.dumps(proxy, ensure_ascii=False)}\n\n"
        "proxy-groups:\n"
        f"  - name: RVG\n"
        f"    type: select\n"
        f"    proxies: ['{name}']\n"
    )


# ── Add config endpoints ──────────────────────────────────────────────────────

def add_config_endpoints(main_mod, app):
    from fastapi import Request, HTTPException, Depends
    from fastapi.responses import Response, PlainTextResponse, JSONResponse

    LINKS = main_mod.LINKS
    LINKS_LOCK = main_mod.LINKS_LOCK
    DEFAULT_PROTOCOL = main_mod.DEFAULT_PROTOCOL
    _request_host_ctx = main_mod._request_host_ctx

    def _get_host(request: Request) -> str:
        h = (
            request.headers.get("x-forwarded-host", "").split(",")[0].strip()
            or request.headers.get("abc", "").strip()
            or request.headers.get("host", "")
            or "127.0.0.1"
        )
        if ":" in h and not h.startswith("["):
            h = h.rsplit(":", 1)[0]
        return h

    @app.get("/debug/headers")
    async def debug_headers(request: Request):
        return JSONResponse({
            "headers": {k: v for k, v in request.headers.items()},
            "host": request.headers.get("host"),
            "x_forwarded_host": request.headers.get("x-forwarded-host"),
            "abc": request.headers.get("abc"),
            "resolved": _get_host(request),
            "ctx": _request_host_ctx.get(""),
        })

    @app.get("/api/storage-diag")
    async def storage_diag(_=Depends(main_mod.require_auth)):
        """عیب‌یابی کامل ذخیره‌سازی/Redis — مخصوص محیط‌های production که لاگ
       شان مستقیم در دسترس نیست. هیچ اطلاعات حساسی برنمی‌گرداند."""
        import importlib.util
        import platform as _platform

        diag: dict = {
            "python": sys.version.split()[0],
            "platform": f"{_platform.system()} {_platform.machine()}",
            "cwd": os.getcwd(),
            "work_dir": WORK_DIR,
            "redis_port": REDIS_PORT,
            "redis_url_env_set": bool(os.environ.get("REDIS_URL", "").strip()),
            "external_redis_txt": os.path.isfile(os.path.join(WORK_DIR, "external_redis.txt")),
            "redis_ping": _redis_alive(),
        }
        try:
            import redis as _r
            diag["redis_pylib"] = {"ok": True,
                                   "version": getattr(_r, "__version__", "?"),
                                   "path": str(getattr(_r, "__file__", "?"))}
        except Exception as e:
            diag["redis_pylib"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        try:
            import redis.asyncio as _ra  # noqa: F401
            diag["redis_asyncio"] = {"ok": True}
        except Exception as e:
            diag["redis_asyncio"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        try:
            diag["pip_available"] = importlib.util.find_spec("pip") is not None
        except Exception:
            diag["pip_available"] = False

        diag["embedded_redis"] = _embedded_redis_report()
        diag["redis_binary_candidates"] = _redis_binary_report()
        bin_path = _find_redis_binary()
        diag["redis_binary_chosen"] = bin_path
        if bin_path:
            try:
                out = subprocess.run([bin_path, "--version"], capture_output=True,
                                     text=True, timeout=10)
                diag["redis_binary_exec_test"] = {
                    "ok": out.returncode == 0,
                    "returncode": out.returncode,
                    "stdout": out.stdout.strip()[:120],
                    "stderr": out.stderr.strip()[:200],
                }
            except Exception as e:
                diag["redis_binary_exec_test"] = {"ok": False,
                                                  "error": f"{type(e).__name__}: {e}"}

        try:
            dd = main_mod.DATA_DIR
            diag["main_data_dir"] = str(dd)
            probe = dd / ".diag_write_test"
            probe.write_text("ok")
            probe.unlink()
            diag["data_dir_writable"] = True
        except Exception as e:
            diag["data_dir_writable"] = False
            diag["data_dir_error"] = f"{type(e).__name__}: {e}"
        try:
            diag["state_file_exists"] = bool(main_mod.DATA_FILE.exists())
        except Exception:
            diag["state_file_exists"] = False
        diag["redis_connected"] = bool(main_mod.REDIS_CONNECTED)
        diag["storage_backend"] = "redis" if main_mod.REDIS_CONNECTED else "file"
        diag["links_count"] = len(main_mod.LINKS)

        try:
            entries = sorted(e.name + ("/" if e.is_dir() else "")
                             for e in os.scandir(WORK_DIR))
            diag["work_dir_entries"] = entries[:80]
            bin_dir = os.path.join(WORK_DIR, "bin")
            if os.path.isdir(bin_dir):
                diag["bin_dir_entries"] = sorted(
                    f"{e.name}:{e.stat().st_size}" for e in os.scandir(bin_dir))[:20]
            vendor_dir = os.path.join(WORK_DIR, "vendor")
            if os.path.isdir(vendor_dir):
                diag["vendor_dir_entries"] = sorted(
                    e.name for e in os.scandir(vendor_dir))[:20]
        except Exception as e:
            diag["work_dir_entries"] = f"error: {type(e).__name__}: {e}"

        try:
            p = os.path.join(WORK_DIR, "redis.log")
            if os.path.isfile(p):
                with open(p, "rb") as fh:
                    fh.seek(0, 2)
                    fh.seek(max(0, fh.tell() - 2000))
                    diag["redis_log_tail"] = fh.read().decode("utf-8", "replace").splitlines()[-15:]
        except Exception:
            pass
        return JSONResponse(diag)

    @app.get("/api/protocols/status")
    async def protocols_status(request: Request):
        """Returns which protocols work through the current gateway.
        xhttp and hysteria don't work through the fcapp gateway because:
        - xhttp needs streaming HTTP response (gateway buffers/blocks it)
        - hysteria needs UDP (gateway only exposes HTTP, UDP outbound blocked)
        """
        host = _get_host(request)
        local = _is_local(host)
        return JSONResponse({
            "host": host,
            "local": local,
            "protocols": {
                "vless-ws": {"works": True, "note": "WebSocket — fully supported"},
                "trojan-ws": {"works": True, "note": "WebSocket — fully supported"},
                "shadowsocks": {"works": True, "note": "WebSocket via v2ray-plugin — fully supported"},
                "xhttp-packet-up": {
                    "works": local,
                    "note": "Streaming HTTP — blocked by gateway in production. Works locally only."
                },
                "xhttp-stream-up": {
                    "works": local,
                    "note": "Streaming HTTP — blocked by gateway in production. Works locally only."
                },
                "trojan-xhttp-packet-up": {
                    "works": local,
                    "note": "Streaming HTTP — blocked by gateway in production. Works locally only."
                },
                "trojan-xhttp-stream-up": {
                    "works": local,
                    "note": "Streaming HTTP — blocked by gateway in production. Works locally only."
                },
                "mtproto": {
                    "works": False,
                    "note": "Needs external TCP proxy (Railway feature) — not available here"
                },
            },
            "recommended": ["vless-ws", "trojan-ws", "shadowsocks"],
            "hysteria": {
                "available": False,
                "note": "Hysteria needs UDP. This gateway only exposes HTTP (port 443→81) and UDP outbound is blocked."
            },
        })

    @app.get("/xray-config/{uuid}")
    async def xray_config(uuid: str, request: Request):
        async with LINKS_LOCK:
            link = LINKS.get(uuid)
        if not link:
            raise HTTPException(404, "link not found")
        host = _get_host(request)
        protocol = link.get("protocol", DEFAULT_PROTOCOL)
        local = _is_local(host)
        cfg = _build_xray_config(uuid, host, protocol, link, local)
        if not cfg:
            raise HTTPException(400, f"unsupported: {protocol}")
        # Add warning for protocols that don't work through the gateway
        warning = None
        if not local and "xhttp" in protocol:
            warning = (
                "⚠️ xhttp needs streaming HTTP response, which the fcapp gateway "
                "blocks. This config WILL NOT WORK in production. "
                "Use vless-ws or trojan-ws instead (they use WebSocket, which works)."
            )
        elif not local and protocol == "mtproto":
            warning = (
                "⚠️ MTProto needs an external TCP proxy (Railway feature), "
                "which is not available in this deployment."
            )
        if warning:
            cfg["_warning"] = warning
            cfg["_recommended"] = "vless-ws"
        return Response(
            content=json.dumps(cfg, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="rvg-{uuid[:8]}.json"'},
        )

    @app.get("/clash/{uuid}")
    async def clash_config(uuid: str, request: Request):
        async with LINKS_LOCK:
            link = LINKS.get(uuid)
        if not link:
            raise HTTPException(404, "link not found")
        host = _get_host(request)
        protocol = link.get("protocol", DEFAULT_PROTOCOL)
        body = _build_clash_config(uuid, host, protocol, link, _is_local(host))
        return PlainTextResponse(
            content=body,
            headers={"Content-Disposition": f'attachment; filename="rvg-{uuid[:8]}.yaml"'},
        )


# ── Redis bootstrap (اختیاری) ─────────────────────────────────────────────────

def _redis_alive(host: str = "127.0.0.1", port: int = REDIS_PORT) -> bool:
    """PING دستی روی پروتکل Redis — بدون نیاز به redis-cli یا پکیج redis."""
    try:
        with socket.create_connection((host, port), timeout=1) as s:
            s.sendall(b"*1\r\n$4\r\nPING\r\n")
            return b"+PONG" in s.recv(16)
    except Exception:
        return False


def _writable_dir(*candidates: str) -> str | None:
    """اولین مسیرِ واقعاً قابل‌نوشتن از بین کاندیدها (برای 이미ج‌های read-only)."""
    for c in candidates:
        if not c:
            continue
        try:
            os.makedirs(c, exist_ok=True)
            probe = os.path.join(c, ".rvg_write_test")
            with open(probe, "w") as f:
                f.write("ok")
            os.unlink(probe)
            return c
        except Exception:
            continue
    return None


def _external_redis_url() -> str:
    """REDIS_URL از env، وگرنه از فایل external_redis.txt (کنار daemon.py یا در
    DATA_DIR). فایل برای Redis خارجی مثل Upstash/Railway است — تنها چیزی که
    بین redeploy های کامل محیط production زنده می‌ماند."""
    url = os.environ.get("REDIS_URL", "").strip()
    if url:
        return url
    for f in (os.path.join(WORK_DIR, "external_redis.txt"),
              os.path.join(os.environ.get("DATA_DIR") or WORK_DIR, "external_redis.txt")):
        try:
            if os.path.isfile(f):
                with open(f, "r", encoding="utf-8") as fh:
                    u = fh.read().strip()
                if u:
                    print(f"[RVG] REDIS_URL read from {f}", file=sys.stderr)
                    return u
        except Exception:
            continue
    return ""


def _redis_binary_report() -> list:
    """گزارش همه‌ی کاندیدهای باینری redis — برای endpoint عیب‌یابی (storage-diag)."""
    candidates = [
        os.path.join(WORK_DIR, "bin", "redis-server"),              # RVG/bin (توسط setup.sh کپی می‌شود)
        os.path.join(WORK_DIR, "redis-bin", "redis-server"),        # اجرای مستقیم از داخل RVG
        os.path.join(WORK_DIR, "..", "redis-bin", "redis-server"),  # اجرای مستقیم از داخل کلون ریپو
        os.path.join(WORK_DIR, "..", "..", "redis-bin", "redis-server"),
        os.path.expanduser("~/.local/bin/redis-server"),
        "/usr/local/bin/redis-server",
        "/usr/bin/redis-server",
    ]
    try:
        which = shutil.which("redis-server")
        if which:
            candidates.append(which)
    except Exception:
        pass
    report = []
    for c in candidates:
        try:
            exists = bool(c) and os.path.isfile(c)
            report.append({"path": c, "exists": exists,
                           "exec_ok": bool(exists and os.access(c, os.X_OK))})
        except Exception:
            report.append({"path": c, "exists": False, "exec_ok": False})
    return report


def _embedded_redis_parts_dir() -> str | None:
    """پوشه‌ی قطعات جاسازی‌شده‌ی redis-server (فایل‌های py) — چون پایپ‌لاین deploy
    بعضی پلتفرم‌ها فایل‌های باینری را از ایمیج حذف می‌کند ولی .pyها را نگه می‌دارد."""
    for d in (os.path.join(WORK_DIR, "vendor", "redisbin"),
              os.path.join(WORK_DIR, "redisbin"),
              os.path.join(WORK_DIR, "..", "vendor", "redisbin")):
        try:
            if os.path.isdir(d):
                return d
        except Exception:
            continue
    return None


def _embedded_redis_report() -> dict:
    """گزارش وضعیت قطعات جاسازی‌شده — برای endpoint عیب‌یابی (storage-diag)."""
    import re as _re
    pd = _embedded_redis_parts_dir()
    if not pd:
        return {"parts_dir": None, "parts": 0}
    try:
        parts = sorted(f for f in os.listdir(pd) if _re.fullmatch(r"part_\d+\.py", f))
        return {"parts_dir": pd, "parts": len(parts)}
    except Exception as e:
        return {"parts_dir": pd, "parts": 0, "error": f"{type(e).__name__}: {e}"}


def _materialize_embedded_redis() -> str | None:
    """بازسازی redis-server از قطعات py (gzip+base64) — آخرین لایه‌ی خودترمیمی.
    خروجی در اولین مسیر قابل‌نوشتن نوشته و اجرایی می‌شود؛ اگر از قبل ساخته شده
    باشد همان مسیر برمی‌گردد (idempotent)."""
    import base64
    import gzip
    import hashlib
    import re as _re

    rep = _embedded_redis_report()
    if not rep.get("parts"):
        return None
    pd = rep["parts_dir"]
    target_dir = _writable_dir(
        os.path.join(WORK_DIR, "bin"),
        os.path.join(tempfile.gettempdir(), "rvg-bin"),
    )
    if not target_dir:
        return None
    target = os.path.join(target_dir, "redis-server")
    try:
        if os.path.isfile(target) and os.path.getsize(target) > 1_000_000 \
                and os.access(target, os.X_OK):
            return target  # از قبل بازسازی شده
        chunks = []
        for name in sorted(f for f in os.listdir(pd) if _re.fullmatch(r"part_\d+\.py", f)):
            with open(os.path.join(pd, name), "r", encoding="utf-8") as fh:
                m = _re.search(r'R\s*=\s*"""(.*?)"""', fh.read(), _re.S)
            if not m or not m.group(1).strip():
                print(f"[RVG] embedded redis part {name} is corrupt — materialization aborted.", file=sys.stderr)
                return None
            chunks.append(m.group(1).strip())
        raw = gzip.decompress(base64.b64decode("".join(chunks)))
        # صحت‌سنجی md5 در صورت وجود part_meta.py
        md5_ok = None
        try:
            meta_path = os.path.join(pd, "part_meta.py")
            if os.path.isfile(meta_path):
                meta: dict = {}
                with open(meta_path, "r", encoding="utf-8") as fh:
                    code = fh.read()
                for line in code.splitlines():
                    line = line.strip()
                    if line.startswith("MD5"):
                        meta["md5"] = line.split("=", 1)[1].strip().strip('"')
                    elif line.startswith("SIZE"):
                        try:
                            meta["size"] = int(line.split("=", 1)[1].strip())
                        except ValueError:
                            pass
                actual = hashlib.md5(raw).hexdigest()
                md5_ok = (meta.get("md5") == actual)
                if meta.get("size"):
                    md5_ok = md5_ok and meta.get("size") == len(raw)
                if not md5_ok:
                    print(f"[RVG] embedded redis md5 mismatch ({actual}) — aborting.", file=sys.stderr)
                    return None
        except Exception:
            pass
        with open(target, "wb") as fh:
            fh.write(raw)
        os.chmod(target, 0o755)
        print(f"[RVG] redis-server materialized from embedded py-parts (md5_ok={md5_ok}) → {target}", file=sys.stderr)
        return target
    except Exception as e:
        print(f"[RVG] embedded redis materialization failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _find_redis_binary() -> str | None:
    """اولین باینری موجود. اجرایی‌ها اولویت دارند؛ اگر هیچ‌کدام اجرایی نبود همان
    مسیر برمی‌گردد — _ensure_redis موقع spawn مشکل exec را دور می‌زند (کپی به tmp).
    اگر هیچ باینری‌ای روی دیسک نبود (deploy باینری‌ها را حذف کرده)، از قطعات
    py جاسازی‌شده بازسازی می‌شود."""
    report = _redis_binary_report()
    exec_ok = next((r["path"] for r in report if r["exec_ok"]), None)
    if exec_ok:
        return exec_ok
    exists_any = next((r["path"] for r in report if r["exists"]), None)
    if exists_any:
        try:
            os.chmod(exists_any, 0o755)
        except Exception:
            pass
        return exists_any
    return _materialize_embedded_redis()


def _spawn_redis(bin_path: str, redis_dir: str, logf=None) -> None:
    cmd = [bin_path, "--port", str(REDIS_PORT), "--bind", "127.0.0.1",
           "--dir", redis_dir, "--appendonly", "yes", "--appendfsync", "everysec"]
    if logf is not None:
        subprocess.Popen(cmd, stdout=logf, stderr=logf, start_new_session=True)
    else:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)


def _ensure_redis():
    """اگر Redis خارجی (env یا external_redis.txt) تعریف شده باشد از همان
    استفاده می‌شود. وگرنه سعی می‌کند Redis محلی را با باینری همراه ریپو بالا
    بیاورد — با AOF (appendonly) تا state بین ری‌استارت‌ها ماندگار بماند.
    اگر باینری در جایش اجرایی نبود (noexec mount)، به tmp کپی و از آنجا اجرا
    می‌شود. اگر هیچ‌کدام نشد، پنل روی فایل محلی کار می‌کند و هیچ‌چیز نمی‌شکند."""
    url = _external_redis_url()
    if url:
        os.environ["REDIS_URL"] = url
        print("[RVG] external REDIS_URL configured — using external Redis.", file=sys.stderr)
        return
    if _redis_alive():
        os.environ["REDIS_URL"] = f"redis://127.0.0.1:{REDIS_PORT}/0"
        print(f"[RVG] Redis already running on 127.0.0.1:{REDIS_PORT} — reusing it.", file=sys.stderr)
        return
    redis_bin = _find_redis_binary()
    if not redis_bin:
        print("[RVG] no redis-server binary found — falling back to local file storage (DATA_DIR).", file=sys.stderr)
        return
    # مسیر AOF: اول DATA_DIR، بعد کنار برنامه، آخر /tmp (همیشه قابل نوشتن)
    redis_dir = _writable_dir(
        os.path.join(os.environ.get("DATA_DIR") or WORK_DIR, "redis"),
        os.path.join(WORK_DIR, "redis"),
        f"{tempfile.gettempdir()}/rvg-redis-{REDIS_PORT}",
    )
    if not redis_dir:
        print("[RVG] no writable dir for Redis AOF — falling back to file storage.", file=sys.stderr)
        return
    logf = None
    try:
        log_dir = _writable_dir(WORK_DIR, tempfile.gettempdir()) or tempfile.gettempdir()
        logf = open(os.path.join(log_dir, "redis.log"), "ab")
    except Exception:
        logf = None
    try:
        _spawn_redis(redis_bin, redis_dir, logf)
    except Exception:
        # mount نوexec یا پرمیژن ناکافی در production — باینری را به tmp کپی
        # می‌کنیم و از آنجا اجرا می‌کنیم (tmp تقریباً همیشه exec اجازه می‌دهد)
        try:
            tmp_bin_dir = os.path.join(tempfile.gettempdir(), "rvg-redis-bin")
            os.makedirs(tmp_bin_dir, exist_ok=True)
            tmp_bin = os.path.join(tmp_bin_dir, "redis-server")
            shutil.copy2(redis_bin, tmp_bin)
            os.chmod(tmp_bin, 0o755)
            _spawn_redis(tmp_bin, redis_dir, logf)
            print(f"[RVG] redis binary not executable in place — copied to {tmp_bin} and started.", file=sys.stderr)
        except Exception as e:
            print(f"[RVG] failed to launch Redis: {e} — falling back to file storage.", file=sys.stderr)
            return
    for _ in range(40):
        if _redis_alive():
            os.environ["REDIS_URL"] = f"redis://127.0.0.1:{REDIS_PORT}/0"
            print(f"[RVG] local Redis up on port {REDIS_PORT} — state on Redis (AOF persistent).", file=sys.stderr)
            return
        time.sleep(0.25)
    print("[RVG] Redis did not answer — falling back to file storage.", file=sys.stderr)


def _ensure_redis_pylib() -> bool:
    """main.py برای صحبت با Redis به پکیج پایتون `redis` نیاز دارد
    (redis.asyncio). ران‌تایمِ build شده‌ی بعضی پلتفرم‌ها از requirements.txt
    قدیمی ساخته شده و این پکیج را ندارد. Self-heal: نصب --target داخل اولین
    مسیر قابل‌نوشتن و اضافه کردن آن به sys.path — قبل از import شدن main."""
    try:
        import redis.asyncio  # noqa: F401
        return True
    except Exception:
        pass
    targets = [
        os.path.join(WORK_DIR, "vendor"),
        os.path.join(WORK_DIR, "pylibs"),
        os.path.join(tempfile.gettempdir(), "rvg-pylibs"),
    ]
    for target in targets:
        td = _writable_dir(target)
        if not td:
            continue
        for extra in ([], ["--break-system-packages"]):
            cmd = [sys.executable, "-m", "pip", "install", "--quiet",
                   "--target", td, *extra, "redis>=5.0.1"]
            try:
                subprocess.run(cmd, check=True, timeout=180,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if td not in sys.path:
                    sys.path.insert(0, td)
                import redis.asyncio  # noqa: F401
                print(f"[RVG] redis python package self-installed into {td}", file=sys.stderr)
                return True
            except Exception:
                continue
    print("[RVG] redis python package unavailable — panel falls back to file storage.", file=sys.stderr)
    return False


# ── serve() — shared by sandbox and production ────────────────────────────────

def serve():
    """Apply all patches and start uvicorn. Called by:
    - sandbox: after double-fork
    - production: directly from instrumentation.ts via `python3 daemon.py --serve`
    """
    # پکیج‌های python خالص همراه ریپو (کلاینت redis) — بدون نیاز به pip/اینترنت.
    # باید قبل از import شدن main روی sys.path باشند (main در import اولیه
    # redis.asyncio را probe می‌کند).
    for _d in ("vendor", "pylibs"):
        _p = os.path.join(WORK_DIR, _d)
        if os.path.isdir(_p) and _p not in sys.path:
            sys.path.insert(0, _p)

    _ensure_redis()
    # پکیج پایتون redis هم باید موجود باشد وگرنه REDIS_URL ست می‌شود ولی main
    # نمی‌تواند وصل شود (aioredis=None). این تابع در صورت نیاز self-heal می‌کند.
    _ensure_redis_pylib()

    # Make sure /data exists (RVG tries to write state there)
    try:
        os.makedirs("/data", exist_ok=True)
    except Exception:
        pass  # Permission denied — RVG handles this gracefully

    os.chdir(WORK_DIR)
    os.environ.setdefault("PYTHONUNBUFFERED", "1")

    sys.path.insert(0, WORK_DIR)

    try:
        import main as rvg_main  # noqa: E402
        from main import app    # noqa: E402
    except Exception as e:
        print(f"[RVG] FATAL: Failed to import main: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

    try:
        patch_config_generation(rvg_main)
        add_config_endpoints(rvg_main, app)
        app.router.redirect_slashes = False
    except Exception as e:
        print(f"[RVG] FATAL: Failed to apply patches: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

    wrapped = TrailingSlashStripper(PublicHostRewriter(app))

    try:
        import uvicorn  # noqa: E402
        uvicorn.run(
            wrapped,
            host="0.0.0.0",
            port=int(PORT),
            log_level="info",
            workers=1,
            loop="asyncio",  # Don't require uvloop (might not be installed)
            http="auto",
        )
    except Exception as e:
        print(f"[RVG] FATAL: uvicorn failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


# ── main() — sandbox entry with double-fork ───────────────────────────────────

def main():
    # --serve flag: production mode (no fork, called by instrumentation.ts)
    if "--serve" in sys.argv:
        serve()
        return

    # Sandbox mode: double-fork to reparent to PID 1 (tini)
    pid = os.fork()
    if pid > 0:
        print(f"[launcher] first-fork child pid={pid}")
        sys.stdout.flush()
        return

    os.setsid()

    pid = os.fork()
    if pid > 0:
        os._exit(0)

    # Grandchild: reparented to init
    devnull = os.open("/dev/null", os.O_RDWR)
    logfd = os.open(LOG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    os.dup2(devnull, 0)
    os.dup2(logfd, 1)
    os.dup2(logfd, 2)
    os.close(devnull)
    os.close(logfd)

    serve()


if __name__ == "__main__":
    main()
