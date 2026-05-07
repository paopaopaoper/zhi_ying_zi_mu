#!/usr/bin/env bash
# 智影字幕 - 部署脚本（rsync 示例）
# 使用前修改 SERVER 变量为目标服务器地址
#
# 用法:
#   chmod +x deploy.sh
#   ./deploy.sh

set -euo pipefail

# ===== 请修改以下配置 =====
SERVER="root@your-server-ip"
REMOTE_DIR="/var/www/zhiying"
# ==========================

echo "==> 同步代码到服务器: $SERVER:$REMOTE_DIR"

rsync -avz --delete \
    --exclude '.env' \
    --exclude '__pycache__' \
    --exclude '.git' \
    --exclude '*.pyc' \
    --exclude 'data/' \
    --exclude 'uploads/' \
    --exclude 'output/' \
    --exclude 'logs/' \
    ./ "$SERVER:$REMOTE_DIR/"

echo "==> 代码同步完成"

echo "==> 安装依赖 & 重启服务"
ssh "$SERVER" << 'EOF'
    cd /var/www/zhiying
    pip install -r requirements.txt -q
    mkdir -p data uploads output logs
    cp -n .env.example .env 2>/dev/null || true
    echo "   请编辑 .env 填写配置: nano /var/www/zhiying/.env"
    echo "   启动服务: sudo systemctl restart zhiying"
    echo "   查看状态: sudo systemctl status zhiying"
EOF

echo "==> 部署完成"
