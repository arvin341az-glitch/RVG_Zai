# botgeneratedomin.py
# ══════════════════════════════════════════════════════════════════════════════
# تولید انبوه دامنه روی Railway — به جای پیدا کردن یک دامنه خاص،
# N تا دامنه‌ی *متفاوت* می‌سازد (فرقی نمی‌کند اسم دامنه چه باشد، فقط یکتا باشد)
# ══════════════════════════════════════════════════════════════════════════════

import asyncio 
import os
import time
import logging
from collections import deque
from typing import Optional

import httpx

import bottokentcpproxy as btp  # از توابع مشترک توکن/اتصال Railway استفاده می‌کنیم

logger = logging.getLogger("RVG-Gateway")

MAX_ATTEMPTS = int(os.environ.get("BOT_DOMAIN_GEN_MAX_ATTEMPTS", 400))
CONCURRENCY = int(os.environ.get("BOT_DOMAIN_GEN_CONCURRENCY", 8))
DEFAULT_TARGET_COUNT = int(os.environ.get("BOT_DOMAIN_GEN_TARGET", 10))
MAX_BACKOFF = 15.0

domain_gen_state = {
    "running": False,
    "progress": 0,
    "attempts": 0,
    "target_count": DEFAULT_TARGET_COUNT,
    "results": [],          # [{domain, port, application_port, id}]
    "error": None,
    "stopped_by_user": False,
}
domain_gen_log: deque = deque(maxlen=300)
_task: Optional[asyncio.Task] = None
_lock: Optional[asyncio.Lock] = None


def _log(msg: str):
    domain_gen_log.append({"time": time.time(), "msg": msg})
    logger.info(f"DomainGen: {msg}")


def get_status() -> dict:
    return {
        **domain_gen_state,
        "has_token": btp.has_saved_token(),
        "logs": list(domain_gen_log)[-100:],
    }


async def _single_attempt(client, token, service_id, environment_id, application_port,
                           attempt_no, results_map: dict, target_count: int):
    try:
        proxy = await btp._create_proxy(client, token, service_id, environment_id, application_port)
    except btp._AuthError as exc:
        return ("fatal", str(exc))
    except btp._RateLimited:
        return "rate_limited"
    except RuntimeError as exc:
        _log(f"⚠ خطای موقتی (GraphQL) در تلاش {attempt_no}: {exc}")
        return "retry"
    except Exception as exc:
        _log(f"⚠ خطای موقتی در تلاش {attempt_no}: {exc}")
        return "retry"

    domain = btp._norm_domain(proxy.get("domain", ""))
    proxy_id = proxy.get("id")

    async with _lock:
        if domain in results_map or len(results_map) >= target_count:
            await btp._delete_proxy(client, token, proxy_id)
            return "discarded"
        results_map[domain] = {
            "domain": domain,
            "port": proxy.get("proxyPort"),
            "application_port": proxy.get("applicationPort"),
            "id": proxy_id,
        }
    _log(f"✅ دامنه‌ی جدید #{len(results_map)}/{target_count}: {domain} — پورت TCP: {proxy.get('proxyPort')}")
    return "added"


async def run_domain_gen_job(token: str, application_port: int, target_count: int):
    global _lock
    _lock = asyncio.Lock()

    domain_gen_state.update({
        "running": True, "progress": 0, "attempts": 0,
        "target_count": target_count, "results": [], "error": None,
        "stopped_by_user": False,
    })
    domain_gen_log.clear()
    _log(f"شروع؛ هدف: {target_count} دامنه — همزمانی: {CONCURRENCY} — پورت اپلیکیشن {application_port} — توکن {btp._mask(token)}")

    try:
        service_id, environment_id = btp.get_service_context()
        _log(f"سرویس شناسایی شد (service={service_id[:8]}… env={environment_id[:8]}…)")
    except RuntimeError as exc:
        domain_gen_state["running"] = False
        domain_gen_state["error"] = str(exc)
        _log(f"❌ {exc}")
        return

    results_map: dict = {}
    backoff = 0.0
    total_attempts = 0

    try:
        async with httpx.AsyncClient() as client:
            while total_attempts < MAX_ATTEMPTS and len(results_map) < target_count:
                batch_size = min(CONCURRENCY, MAX_ATTEMPTS - total_attempts)
                tasks = []
                for _ in range(batch_size):
                    total_attempts += 1
                    tasks.append(_single_attempt(
                        client, token, service_id, environment_id, application_port,
                        total_attempts, results_map, target_count,
                    ))

                domain_gen_state["attempts"] = total_attempts
                domain_gen_state["progress"] = min(99, int(len(results_map) / target_count * 100))

                results = await asyncio.gather(*tasks, return_exceptions=True)

                if len(results_map) >= target_count:
                    break

                fatal_error = None
                any_rate_limited = False
                for r in results:
                    if isinstance(r, Exception):
                        _log(f"⚠ خطای غیرمنتظره: {r}")
                        continue
                    if isinstance(r, tuple) and r[0] == "fatal":
                        fatal_error = r[1]
                    elif r == "rate_limited":
                        any_rate_limited = True

                if fatal_error:
                    domain_gen_state["running"] = False
                    domain_gen_state["error"] = fatal_error
                    _log(f"❌ توقف: {fatal_error}")
                    return

                if any_rate_limited:
                    backoff = min(MAX_BACKOFF, max(1.0, backoff * 1.7 if backoff else 1.0))
                    _log(f"⏳ ریت‌لیمیت ریلوی — {backoff:.1f} ثانیه صبر می‌کنیم...")
                    await asyncio.sleep(backoff)
                else:
                    backoff = 0.0

        domain_gen_state.update({
            "running": False,
            "progress": 100,
            "results": list(results_map.values()),
        })
        if len(results_map) < target_count:
            domain_gen_state["error"] = (
                f"فقط {len(results_map)} از {target_count} دامنه پیدا شد (بعد از {total_attempts} تلاش)"
            )
            _log(f"⚠ {domain_gen_state['error']}")
        else:
            _log(f"✅ هر {target_count} دامنه با موفقیت ساخته شد")

    except asyncio.CancelledError:
        domain_gen_state.update({
            "running": False,
            "results": list(results_map.values()),
            "error": "فرآیند توسط کاربر متوقف شد",
            "stopped_by_user": True,
        })
        _log("⏹ فرآیند توسط کاربر متوقف شد")


def start_job(token: Optional[str], application_port: int, target_count: int = DEFAULT_TARGET_COUNT):
    global _task
    token = (token or "").strip()
    if not token:
        token = btp.load_token() or ""
    if not token:
        raise RuntimeError("توکن Railway وارد نشده و توکن ذخیره‌شده‌ای هم وجود ندارد")
    if domain_gen_state["running"]:
        raise RuntimeError("یک فرآیند ساخت دامنه از قبل در حال اجراست")
    if target_count < 1:
        raise RuntimeError("تعداد دامنه باید حداقل ۱ باشد")

    btp.save_token(token)
    _task = asyncio.create_task(run_domain_gen_job(token, application_port, target_count))
    return _task


def stop_job() -> bool:
    global _task
    if _task and not _task.done():
        _task.cancel()
        return True
    return False