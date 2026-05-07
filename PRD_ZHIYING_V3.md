# 智影字幕 · 项目 PRD v3.0（面向 AI 生成代码）

## 一、核心约束（AI 必须遵守）

1. **最小化原则**  
   - 不引入 Redis / Celery / Docker  
   - 不引入额外外部服务  
   - 不自动执行真实删除命令（只生成清理脚本）

2. **环境分离原则（最重要）**  
   - 代码中**禁止**出现任何硬编码路径（Windows 或 Linux）  
   - 所有目录路径必须通过环境变量读取  
   - 本地与服务器使用同一份代码，通过不同 `.env` 区分

3. **项目角色**  
   - Claude Code：生成代码、systemd、部署脚本、nginx 片段  
   - 你 + DeepSeek Web：架构、部署、上线

## 二、环境与路径抽象（必须严格实现）

### 1. 本地开发环境
- 根目录：`D:\code\claude-code-file`
- `.env` 示例：
```ini
ENV=development
DATA_DIR=D:/code/claude-code-file/data
UPLOAD_DIR=D:/code/claude-code-file/uploads
OUTPUT_DIR=D:/code/claude-code-file/output
LOG_FILE=D:/code/claude-code-file/logs/app.log
WHISPER_API_KEY=sk-xxx
WHISPER_BASE_URL=https://api.aihubmix.com/v1
```

### 2. 生产环境（云服务器）
- 根目录：/var/www/zhiying

- `.env` 示例：
```ini
ENV=production
DATA_DIR=/var/www/zhiying/data
UPLOAD_DIR=/var/www/zhiying/uploads
OUTPUT_DIR=/var/www/zhiying/output
LOG_FILE=/var/log/zhiying.log
WHISPER_API_KEY=sk-xxx
WHISPER_BASE_URL=https://api.aihubmix.com/v1
```

### 3. 代码实现要求
- 所有路径使用 os.getenv() + Path 拼接
- 启动时检查必需环境变量，缺失则报错退出
- 提供 .env.example 模板文件


## 三、技术栈（固定）

| 类别 | 选择 |
|------|------|
| 后端 | Python 3.10 + FastAPI |
| 数据库 | SQLite（路径由 `DATA_DIR` 决定） |
| 前端 | HTML + TailwindCSS + 原生 JS |
| 异步任务 | FastAPI `BackgroundTasks` |
| ASR 服务 | aihubmix 中转 API（`whisper-1`） |
| 部署 | Nginx + uvicorn（systemd） |

---

## 四、目录结构（AI 生成代码时需匹配）

```text
{DATA_DIR}/
├── data.db

{UPLOAD_DIR}/
└── {task_id}.mp4

{OUTPUT_DIR}/
└── {task_id}_sub.mp4

项目根目录/
├── main.py
├── requirements.txt
├── .env.example
├── static/
│   └── index.html
└── scripts/
    └── clean_files.sh

```

注：{} 表示从环境变量读取的具体值。



## 五、数据库设计（SQLite）

### users 表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | PK |
| phone | TEXT | UNIQUE |
| created_at | DATETIME | |

### tasks 表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | PK，UUID |
| user_id | INTEGER | FK |
| status | TEXT | pending / processing / done / failed |
| video_path | TEXT | |
| srt_content | TEXT | |
| output_video_path | TEXT | |
| error_message | TEXT | |
| created_at | DATETIME | |

---

## 六、API 接口规范（第一部分）

### 1. `POST /send-code`（Mock）
- 请求：`{ "phone": "13800138000" }`
- 响应：`{ "message": "mock code 123456" }`
- 说明：P0 不接入真实短信，验证码恒为 `123456`

### 2. `POST /login`
- 请求：`{ "phone": "...", "code": "123456" }`
- 响应：`{ "user_id": 1, "message": "ok" }`
- 说明：若手机号不存在则自动注册

### 3. `POST /upload`
- 请求：`multipart/form-data`（video + user_id）
- 响应：`{ "task_id": "uuid" }`
- 行为：
  - 保存原始视频到 `{UPLOAD_DIR}/{task_id}.mp4`
  - 创建 task 记录，状态 `pending`
  - 触发后台 Whisper 转写

### 4. `GET /task/{task_id}`
- 响应：
```json
{
  "status": "done",
  "srt_content": "...",
  "output_video_url": "/output/xxx.mp4"
}
```

### 5. POST /burn
请求：{ "task_id": "uuid", "style": {...} }

响应：{ "output_video_url": "..." }

说明：调用 FFmpeg 烧录字幕，输出到 {OUTPUT_DIR}/{task_id}_sub.mp4

### 6. POST /create-order（Mock 支付预留）
请求：{ "user_id": 1, "task_id": "uuid", "amount": 29 }

响应：{ "order_id": "xxx", "mock_pay_url": "/mock-pay?order_id=xxx" }

### 7. POST /payment-callback（Mock）
请求：{ "order_id": "xxx", "status": "success" }

响应：{ "message": "ok" }

### 8. GET /health
响应：{ "status": "ok" }


## 七、Whisper 调用规范
- Base URL：https://api.aihubmix.com/v1
- 模型：whisper-1
- 兼容 OpenAI SDK，只修改 base_url 与 api_key
- 超时时间：120 秒
- 输出格式：srt


## 八、前端体验要求

### 1. 上传与轮询
- 轮询间隔：2 秒
- 最大轮询次数：300 次（10 分钟）
- 超时提示：“任务可能失败，请联系支持”

### 2. 成功通知
- 浏览器 Notification（需请求权限）
- 内置提示音（`Audio` 对象）

### 3. 耗时提示文案（固定）
> “该过程耗时较长，您可以喝杯茶，眺望远处休息一下~”

---

## 九、可观测性（你明确要求）

- 所有错误写入 `{LOG_FILE}`（由环境变量指定）
- 任务失败时 `tasks.error_message` 记录异常堆栈
- `/health` 接口用于负载均衡与监控

---

## 十、文件生命周期与清理

- 原始视频：`{UPLOAD_DIR}/{task_id}.mp4`
- 烧录视频：`{OUTPUT_DIR}/{task_id}_sub.mp4`
- 保留时长：**24 小时**
- 清理方式：
  - 提供 `scripts/clean_files.sh` 脚本
  - 脚本使用 `find -mtime +1`
  - AI **不自动执行**，只生成脚本


## 十一、部署与交付物

### AI 必须输出以下文件

1. `main.py`
2. `requirements.txt`
3. `.env.example`
4. `static/index.html`
5. `scripts/clean_files.sh`
6. `systemd/zhiying.service`
7. `deploy.sh`（rsync 示例脚本）
8. `README.md`（含完整部署步骤）

### README 必须包含
- 本地与服务器 `.env` 配置说明
- 如何初始化数据库
- 如何启动服务（uvicorn / systemd）
- 如何设置清理脚本的 crontab

---

## 十二、AI 不负责的内容（边界清晰）

- 真实 SSL 证书申请与配置
- 阿里云安全组规则
- 域名 DNS 解析
- Nginx 的全量配置（只提供片段）
- 生产环境的手动部署操作

---

## 十三、验收标准（AI 必须自测通过）

- [ ] 本地启动后，`/health` 返回 200
- [ ] 上传视频能生成 task_id，并在 30 秒内转写完成（Whisper）
- [ ] 前端轮询能正确展示状态变化
- [ ] 调用 `/burn` 能生成带字幕视频（FFmpeg）
- [ ] 不存在任何硬编码路径
- [ ] 缺失 `.env` 时启动报错并退出