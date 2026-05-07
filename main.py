"""智影字幕 - FastAPI 后端主程序"""

import logging
import os
import sqlite3
import subprocess
import sys
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# 加载 .env （优先项目根目录）
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# 环境变量验证
# ---------------------------------------------------------------------------
REQUIRED_ENV = ["DATA_DIR", "UPLOAD_DIR", "OUTPUT_DIR", "WHISPER_API_KEY", "WHISPER_BASE_URL"]
MISSING = [k for k in REQUIRED_ENV if not os.getenv(k)]
if MISSING:
    print(f"[FATAL] 缺少必需的环境变量: {', '.join(MISSING)}", file=sys.stderr)
    print("[HINT] 请复制 .env.example 为 .env 并填写配置", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# 基于环境变量的路径
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.getenv("DATA_DIR"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR"))
LOG_FILE = Path(os.getenv("LOG_FILE"))

# 自动创建目录
for d in [DATA_DIR, UPLOAD_DIR, OUTPUT_DIR, LOG_FILE.parent]:
    d.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "data.db"

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger("zhiying")

# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL UNIQUE,
            created_at DATETIME DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','processing','done','failed')),
            video_path TEXT,
            srt_content TEXT,
            output_video_path TEXT,
            error_message TEXT,
            created_at DATETIME DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------
class SendCodeRequest(BaseModel):
    phone: str


class LoginRequest(BaseModel):
    phone: str
    code: str


class BurnRequest(BaseModel):
    task_id: str
    style: dict | None = None


class CreateOrderRequest(BaseModel):
    user_id: int
    task_id: str
    amount: int


class PaymentCallbackRequest(BaseModel):
    order_id: str
    status: str


# ---------------------------------------------------------------------------
# 应用生命周期
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("数据库初始化完成")
    yield


app = FastAPI(title="智影字幕 API", version="3.0.0", lifespan=lifespan)

# 挂载静态文件和输出目录（开发模式用；生产用 Nginx 代理）
app.mount("/static", StaticFiles(directory="static", html=True), name="static")
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")


@app.get("/", response_class=HTMLResponse)
async def root():
    """根路径返回前端页面"""
    index_path = Path("static") / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>智影字幕</h1><p>前端页面未找到</p>")


# ================================ API 路由 ================================


@app.post("/send-code")
async def send_code(body: SendCodeRequest):
    """Mock 发送验证码，恒为 123456"""
    logger.info("Mock 发送验证码: phone=%s", body.phone)
    return {"message": "mock code 123456"}


@app.post("/login")
async def login(body: LoginRequest):
    """登录/注册，验证码为 123456"""
    if body.code != "123456":
        raise HTTPException(status_code=400, detail="验证码错误")

    conn = get_db()
    try:
        cur = conn.execute("SELECT id FROM users WHERE phone = ?", (body.phone,))
        row = cur.fetchone()
        if row:
            user_id = row["id"]
            logger.info("用户登录: id=%d phone=%s", user_id, body.phone)
        else:
            cur = conn.execute("INSERT INTO users (phone) VALUES (?)", (body.phone,))
            conn.commit()
            user_id = cur.lastrowid
            logger.info("新用户注册: id=%d phone=%s", user_id, body.phone)
        return {"user_id": user_id, "message": "ok"}
    finally:
        conn.close()


@app.post("/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    user_id: int = Form(...),
):
    """上传视频并触发后台 Whisper 转写"""
    task_id = str(uuid.uuid4())
    ext = Path(video.filename).suffix if video.filename else ".mp4"
    video_path = UPLOAD_DIR / f"{task_id}{ext}"

    # 保存文件
    content = await video.read()
    video_path.write_bytes(content)
    logger.info("视频已保存: task=%s size=%d bytes", task_id, len(content))

    # 创建任务
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO tasks (id, user_id, status, video_path) VALUES (?, ?, 'pending', ?)",
            (task_id, user_id, str(video_path)),
        )
        conn.commit()
    finally:
        conn.close()

    # 后台执行 Whisper 转写
    background_tasks.add_task(process_whisper, task_id, str(video_path))

    return {"task_id": task_id}


@app.get("/task/{task_id}")
async def get_task(task_id: str):
    """轮询任务状态"""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")

    result = {
        "status": row["status"],
        "srt_content": row["srt_content"],
    }
    if row["output_video_path"]:
        video_name = Path(row["output_video_path"]).name
        result["output_video_url"] = f"/output/{video_name}"
    if row["error_message"]:
        result["error_message"] = row["error_message"]
    return result


@app.post("/burn")
async def burn_subtitles(body: BurnRequest):
    """FFmpeg 烧录字幕到视频"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (body.task_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not row["srt_content"]:
        raise HTTPException(status_code=400, detail="字幕内容为空，请先完成转写")
    if not row["video_path"]:
        raise HTTPException(status_code=400, detail="原始视频路径丢失")

    video_path = Path(row["video_path"])
    if not video_path.exists():
        raise HTTPException(status_code=400, detail="原始视频文件不存在")

    output_path = OUTPUT_DIR / f"{body.task_id}_sub.mp4"
    srt_path = OUTPUT_DIR / f"{body.task_id}.srt"

    # 写入临时 SRT 文件
    srt_path.write_text(row["srt_content"], encoding="utf-8")

    # FFmpeg 烧录字幕
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"subtitles={srt_path.name}",
        "-c:a", "copy",
        str(output_path),
    ]
    logger.info("FFmpeg 开始烧录: task=%s", body.task_id)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(OUTPUT_DIR))

    if result.returncode != 0:
        logger.error("FFmpeg 失败: %s", result.stderr)
        raise HTTPException(status_code=500, detail=f"字幕烧录失败: {result.stderr[:500]}")
    logger.info("FFmpeg 烧录完成: task=%s", body.task_id)

    # 更新任务
    conn = get_db()
    try:
        conn.execute(
            "UPDATE tasks SET output_video_path = ? WHERE id = ?",
            (str(output_path), body.task_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {"output_video_url": f"/output/{output_path.name}"}


# ---------------------------------------------------------------------------
# Mock 支付
# ---------------------------------------------------------------------------
ORDERS: dict = {}


@app.post("/create-order")
async def create_order(body: CreateOrderRequest):
    """创建 Mock 订单"""
    order_id = str(uuid.uuid4())
    ORDERS[order_id] = {
        "user_id": body.user_id,
        "task_id": body.task_id,
        "amount": body.amount,
        "status": "pending",
    }
    logger.info("订单创建: order=%s amount=%d", order_id, body.amount)
    return {
        "order_id": order_id,
        "mock_pay_url": f"/mock-pay?order_id={order_id}",
    }


@app.post("/payment-callback")
async def payment_callback(body: PaymentCallbackRequest):
    """Mock 支付回调"""
    if body.order_id not in ORDERS:
        raise HTTPException(status_code=404, detail="订单不存在")
    ORDERS[body.order_id]["status"] = body.status
    logger.info("支付回调: order=%s status=%s", body.order_id, body.status)
    return {"message": "ok"}


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok"}


# ============================== 后台任务 ==============================


def process_whisper(task_id: str, video_path: str):
    """调用 aihubmix Whisper API 进行语音转写"""
    conn = get_db()
    try:
        # 更新状态为 processing
        conn.execute("UPDATE tasks SET status='processing' WHERE id=?", (task_id,))
        conn.commit()

        api_key = os.getenv("WHISPER_API_KEY")
        base_url = os.getenv("WHISPER_BASE_URL")

        headers = {"Authorization": f"Bearer {api_key}"}
        files = {"file": (f"{task_id}.mp4", open(video_path, "rb"), "video/mp4")}
        data = {"model": "whisper-1", "response_format": "srt"}

        logger.info("Whisper 请求开始: task=%s", task_id)
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"{base_url}/audio/transcriptions",
                headers=headers,
                files=files,
                data=data,
            )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Whisper API 返回 {resp.status_code}: {resp.text[:300]}"
            )

        srt_text = resp.text.strip()
        logger.info(
            "Whisper 完成: task=%s 长度=%d 字符", task_id, len(srt_text)
        )

        # 更新成功
        conn.execute(
            "UPDATE tasks SET status='done', srt_content=? WHERE id=?",
            (srt_text, task_id),
        )
        conn.commit()

    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Whisper 失败: task=%s error=%s", task_id, tb)
        conn.execute(
            "UPDATE tasks SET status='failed', error_message=? WHERE id=?",
            (tb, task_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=["data/*", "uploads/*", "output/*", "logs/*", ".env"],
    )
