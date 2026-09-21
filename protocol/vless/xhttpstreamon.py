# xhttpstreamon.py
# ══════════════════════════════════════════════════════════════════════════════
# XHTTP — دانلینک (GET پیوسته که داده‌های سرور مقصد رو به کلاینت stream می‌کنه)
# برای VLESS. منطق اصلی (session, quota, adaptive flow) در xhttp_core.py قرار
# دارد؛ این فایل فقط route رو تعریف می‌کنه و از _downstream_gen مصرف می‌کنه.
#
# برای کمترین تاخیر (مناسب پلتفرم‌هایی مثل اینستاگرام/یوتیوب/تیک‌تاک با حجم
# بالا و تلگرام با حجم کم و پیام‌های کوچیک):
#   - بدون هیچ بافرینگ اضافه در لایه‌ی HTTP (headers از _resp_headers که
#     x-accel-buffering: no و cache-control: no-cache/no-store داره)
#   - StreamingResponse مستقیم از async generator که هر chunk رو به محض
#     رسیدن از TCP مقصد yield می‌کنه (بدون جمع‌کردن/batch کردن اضافه)
#   - همون _AdaptiveFlow/_QuotaGate که روی مسیر آپلود هست، اینجا لازم نیست
#     چون این مسیر فقط خواندن از صف داخلی (down_q) هست، نه سوکت خام
# ══════════════════════════════════════════════════════════════════════════════

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from main import error_logs
from protocol.vless.xhttp_core import (
    _check_link,
    _downstream_gen,
    _get_or_create_session,
    _req_client_ip,
    _resp_headers,
    ensure_reaper,
)

router = APIRouter()


# ══════════════════════════════ STREAM-ONE (GET پیوسته‌ی دانلینک) ══════════════════════════════
@router.get("/xhttp-siz10/{mode}/{uuid}/{session_id}")
async def xhttp_downlink(mode: str, uuid: str, session_id: str, request: Request):
    ensure_reaper()
    try:
        await _check_link(uuid)
    except HTTPException:
        raise
    except Exception as exc:
        error_logs.append({"error": f"xhttp downlink check_link failed: {exc}"})
        raise HTTPException(status_code=403, detail="not authorized")

    sess = await _get_or_create_session(uuid, mode, session_id, _req_client_ip(request))
    if sess.get("closed"):
        raise HTTPException(status_code=404, detail="session closed")

    headers = _resp_headers("chrome")
    return StreamingResponse(
        _downstream_gen(sess),
        media_type=headers.pop("content-type", "application/grpc"),
        headers=headers,
    )
