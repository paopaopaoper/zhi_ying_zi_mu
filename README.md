# 智影字幕 · AI 智能字幕生成

基于 FastAPI + Whisper API 的智能视频字幕生成工具。

## 目录结构

```
项目根目录/
├── main.py              # FastAPI 后端主程序
├── requirements.txt     # Python 依赖
├── .env.example         # 环境变量模板
├── deploy.sh            # 部署脚本（rsync）
├── README.md
├── static/
│   └── index.html       # 前端页面
├── scripts/
│   ├── clean_files.sh   # 文件清理脚本（24h 过期）
│   └── init_db.py       # 手动初始化数据库
└── systemd/
    └── zhiying.service  # systemd 服务单元
```

## 快速开始（本地开发）

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

需要系统安装 [FFmpeg](https://ffmpeg.org/download.html) 用于字幕烧录。

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，主要修改 `WHISPER_API_KEY` 为你的 aihubmix API Key：

```ini
ENV=development
DATA_DIR=./data
UPLOAD_DIR=./uploads
OUTPUT_DIR=./output
LOG_FILE=./logs/app.log
WHISPER_API_KEY=sk-your-key-here
WHISPER_BASE_URL=https://api.aihubmix.com/v1
```

### 3. 启动服务

```bash
python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

访问 http://localhost:8000/static/index.html

## 生产部署（云服务器）

### 环境配置

服务器路径：`/var/www/zhiying`

`.env` 示例：

```ini
ENV=production
DATA_DIR=/var/www/zhiying/data
UPLOAD_DIR=/var/www/zhiying/uploads
OUTPUT_DIR=/var/www/zhiying/output
LOG_FILE=/var/log/zhiying.log
WHISPER_API_KEY=sk-xxx
WHISPER_BASE_URL=https://api.aihubmix.com/v1
```

### 部署步骤

```bash
# 1. 修改 deploy.sh 中的 SERVER 地址
# 2. 执行部署
./deploy.sh

# 3. SSH 到服务器，编辑 .env
nano /var/www/zhiying/.env

# 4. 配置 systemd 服务
sudo cp systemd/zhiying.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable zhiying
sudo systemctl start zhiying

# 5. 查看状态
sudo systemctl status zhiying
```

### Nginx 反向代理参考

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 500M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /static/ {
        alias /var/www/zhiying/static/;
    }

    location /output/ {
        alias /var/www/zhiying/output/;
        add_header Cache-Control "public, max-age=3600";
    }
}
```

### 设置定时清理

```bash
crontab -e
# 添加以下行（每天凌晨 3 点清理 24 小时前的文件）
0 3 * * * /var/www/zhiying/scripts/clean_files.sh >> /var/log/zhiying-clean.log 2>&1
```

## 数据库初始化

服务启动时自动创建表。如需手动初始化：

```bash
python -c "
from main import init_db
init_db()
print('数据库初始化完成')
"
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /send-code | 发送验证码（Mock，恒为 123456） |
| POST | /login | 登录/注册 |
| POST | /upload | 上传视频 |
| GET  | /task/{id} | 查询任务状态 |
| POST | /burn | 烧录字幕 |
| POST | /create-order | 创建订单（Mock） |
| POST | /payment-callback | 支付回调（Mock） |
| GET  | /health | 健康检查 |

## 技术栈

- **后端**: Python 3.10+ / FastAPI / SQLite
- **前端**: HTML + TailwindCSS + 原生 JavaScript
- **ASR**: aihubmix 中转 Whisper-1 API
- **字幕烧录**: FFmpeg
- **部署**: Nginx + uvicorn (systemd)
