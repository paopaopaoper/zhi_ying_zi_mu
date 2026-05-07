#!/usr/bin/env bash
# 智影字幕 - 清理 24 小时前的过期文件
# 使用方式：
#   chmod +x scripts/clean_files.sh
#   ./scripts/clean_files.sh
#
# 设置定时任务（每天凌晨 3 点执行）：
#   crontab -e
#   0 3 * * * /var/www/zhiying/scripts/clean_files.sh >> /var/log/zhiying-clean.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 加载环境变量
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# 默认路径（可被 .env 覆盖）
UPLOAD_DIR="${UPLOAD_DIR:-$PROJECT_DIR/uploads}"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_DIR/output}"
LOG_FILE="${LOG_FILE:-$PROJECT_DIR/logs/app.log}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

log "开始清理过期文件..."

UPLOAD_BEFORE=$(find "$UPLOAD_DIR" -type f -mtime +1 2>/dev/null | wc -l)
OUTPUT_BEFORE=$(find "$OUTPUT_DIR" -type f -mtime +1 2>/dev/null | wc -l)

find "$UPLOAD_DIR" -type f -mtime +1 -delete 2>/dev/null
find "$OUTPUT_DIR" -type f -mtime +1 -delete 2>/dev/null

log "清理完成: 上传目录删除 ${UPLOAD_BEFORE} 个, 输出目录删除 ${OUTPUT_BEFORE} 个"
