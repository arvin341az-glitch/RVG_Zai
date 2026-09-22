#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# RVG backup restore — برگرداندن یک اسنپ‌شات از RVG/backups
# ══════════════════════════════════════════════════════════════════════════════
# Usage:
#   bash RVG/restore-backup.sh                 → لیست بکاپ‌های موجود
#   bash RVG/restore-backup.sh <file.tar.gz>   → بازگردانی آن بکاپ
#
# بازگردانی = استخراج data/ از بکاپ. اگر پنل در حال اجرا باشد، سوپروایزر
# در چرخه‌ی بعدی (حداکثر ۶۰ ثانیه) state را با state جدید بوت می‌کند؛
# برای اعمال فوری: bash RVG/restore-backup.sh <file> --restart
# ══════════════════════════════════════════════════════════════════════════════

RVG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$RVG_DIR/backups"
DATA_DIR="$RVG_DIR/data"

if [ -z "$1" ]; then
    echo "📦 بکاپ‌های موجود (جدیدترین اول):"
    ls -1ht "$BACKUP_DIR"/rvg-data-*.tar.gz 2>/dev/null || echo "  (هیچ بکاپی وجود ندارد)"
    echo ""
    echo "برای بازگردانی:  bash RVG/restore-backup.sh <نام-فایل>"
    exit 0
fi

SRC="$1"
[ -f "$SRC" ] || SRC="$BACKUP_DIR/$(basename "$1")"
if [ ! -f "$SRC" ]; then
    echo "❌ بکاپ پیدا نشد: $1"
    exit 1
fi

echo "💾 بکاپ فعلی قبل از بازگردانی ذخیره می‌شود..."
stamp=$(date +%Y%m%d-%H%M%S)
[ -d "$DATA_DIR" ] && tar -czf "$BACKUP_DIR/rvg-data-before-restore-$stamp.tar.gz" -C "$RVG_DIR" data 2>/dev/null

echo "♻️  بازگردانی از: $SRC"
tar -xzf "$SRC" -C "$RVG_DIR" || { echo "❌ استخراج ناموفق بود"; exit 1; }
echo "✅ data/ بازگردانی شد"

if [ "$2" = "--restart" ]; then
    echo "🔄 ری‌استارت گیت‌وی برای اعمال state..."
    pkill -f "python3 daemon.py" 2>/dev/null
    echo "   سوپروایزر تا ۳ ثانیه دیگر آن را بالا می‌آورد."
fi
echo "🎉 تمام"
