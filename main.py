"""智影字幕 - FastAPI 后端主程序"""
import logging
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

REQUIRED_ENV = ["DATA_DIR", "UPLOAD_DIR", "OUTPUT_DIR", "WHISPER_API_KEY", "WHISPER_BASE_URL"]
MISSING = [k for k in REQUIRED_ENV if not os.getenv(k)]
if MISSING:
    print(f"[FATAL] 缺少必需的环境变量: {', '.join(MISSING)}", file=sys.stderr)
    sys.exit(1)

DATA_DIR = Path(os.getenv("DATA_DIR"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR"))
LOG_FILE = Path(os.getenv("LOG_FILE"))

for d in [DATA_DIR, UPLOAD_DIR, OUTPUT_DIR, LOG_FILE.parent]:
    d.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "data.db"
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "30"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "500")) * 1024 * 1024
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger("zhiying")

# ---------------------------------------------------------------------------
# FFmpeg 路径检测（优先项目 bin/ 目录，回退系统 PATH）
# ---------------------------------------------------------------------------
FFMPEG_PATH = None
FFPROBE_PATH = None
_project_bin = Path(__file__).parent / "bin"
if (_project_bin / "ffmpeg.exe").exists():
    FFMPEG_PATH = str(_project_bin / "ffmpeg.exe")
    FFPROBE_PATH = str(_project_bin / "ffprobe.exe")
    logger.info("使用项目内置 FFmpeg: %s", FFMPEG_PATH)
elif (_project_bin / "ffmpeg").exists():
    FFMPEG_PATH = str(_project_bin / "ffmpeg")
    FFPROBE_PATH = str(_project_bin / "ffprobe")
    logger.info("使用项目内置 FFmpeg: %s", FFMPEG_PATH)
else:
    FFMPEG_PATH = "ffmpeg"
    FFPROBE_PATH = "ffprobe"
    logger.info("使用系统 PATH 中的 FFmpeg")

# ---------------------------------------------------------------------------
# 会员与价格配置（两档）
# ---------------------------------------------------------------------------
MEMBERSHIP_CONFIG = {
    "free": {
        "name": "Free",
        "monthly_quota": 0,
        "initial_quota": 300,
        "can_burn": False,
        "can_edit_subtitles": False,
        "high_precision": False,
        "can_custom_style": False,
        "carryover_months": 0,
        "max_task_duration": 600,
        "priority": 0,
        "retention_days": 3,
        "price": 0,
    },
    "professional": {
        "name": "专业会员",
        "monthly_quota": 3000,
        "initial_quota": 3000,
        "can_burn": True,
        "can_edit_subtitles": True,
        "high_precision": True,
        "can_custom_style": False,
        "carryover_months": 0,
        "max_task_duration": 1800,
        "priority": 1,
        "retention_days": 7,
        "price": 1900,
    },
    "premium": {
        "name": "高级会员",
        "monthly_quota": 3000,
        "initial_quota": 3000,
        "can_burn": True,
        "can_edit_subtitles": True,
        "high_precision": True,
        "can_custom_style": True,
        "carryover_months": 1,
        "max_task_duration": 1800,
        "priority": 2,
        "retention_days": 15,
        "price": 2900,
    },
}

TOPUP_PACKAGES = {
    "small": {"name": "小额包", "seconds": 600, "price": 990},
    "medium": {"name": "中额包", "seconds": 1500, "price": 1990},
    "large": {"name": "大额包", "seconds": 3600, "price": 3990},
}

# ---------------------------------------------------------------------------
# 字幕样式定义（20 种）
# ---------------------------------------------------------------------------
SUBTITLE_STYLES = [
    {"id": 1, "name": "白色经典", "font": "Arial", "font_size": 18, "primary_color": "&H00FFFFFF", "outline_color": "&H00000000", "back_color": "&H80000000", "bold": 0, "alignment": 2, "description": "白字黑边，底部居中"},
    {"id": 2, "name": "黄色醒目", "font": "Arial", "font_size": 20, "primary_color": "&H0000FFFF", "outline_color": "&H00000000", "back_color": "&H80000000", "bold": 1, "alignment": 2, "description": "黄色加粗，突出显示"},
    {"id": 3, "name": "蓝色科技", "font": "Arial", "font_size": 18, "primary_color": "&H00FF8800", "outline_color": "&H00333333", "back_color": "&H00000000", "bold": 0, "alignment": 2, "description": "科技蓝，深灰描边"},
    {"id": 4, "name": "绿色清新", "font": "Arial", "font_size": 18, "primary_color": "&H0000CC66", "outline_color": "&H00224422", "back_color": "&H80000000", "bold": 0, "alignment": 2, "description": "清新绿色，半透明底"},
    {"id": 5, "name": "粉色温柔", "font": "Arial", "font_size": 18, "primary_color": "&H009966FF", "outline_color": "&H00442244", "back_color": "&H00000000", "bold": 0, "alignment": 2, "description": "柔粉色，优雅气质"},
    {"id": 6, "name": "金色典雅", "font": "Times New Roman", "font_size": 18, "primary_color": "&H0033CCFF", "outline_color": "&H00443322", "back_color": "&H80000000", "bold": 0, "alignment": 2, "description": "金色衬线字体，典雅风"},
    {"id": 7, "name": "红色强调", "font": "Arial", "font_size": 20, "primary_color": "&H000000FF", "outline_color": "&H00000000", "back_color": "&H80000000", "bold": 1, "alignment": 2, "description": "红色加粗，适合警示内容"},
    {"id": 8, "name": "灰色低调", "font": "Arial", "font_size": 16, "primary_color": "&H00CCCCCC", "outline_color": "&H00333333", "back_color": "&H00000000", "bold": 0, "alignment": 2, "description": "浅灰细字，不抢画面"},
    {"id": 9, "name": "白色粗体", "font": "Arial", "font_size": 20, "primary_color": "&H00FFFFFF", "outline_color": "&H00000000", "back_color": "&H00000000", "bold": 1, "alignment": 2, "description": "白色加粗，清晰易读"},
    {"id": 10, "name": "半透明底", "font": "Arial", "font_size": 18, "primary_color": "&H00FFFFFF", "outline_color": "&H00000000", "back_color": "&HBB000000", "bold": 0, "alignment": 2, "description": "黑色半透明背景衬底"},
    {"id": 11, "name": "底部大字", "font": "Arial", "font_size": 24, "primary_color": "&H00FFFFFF", "outline_color": "&H00000000", "back_color": "&H80000000", "bold": 0, "alignment": 2, "description": "底部大号字体"},
    {"id": 12, "name": "顶部字幕", "font": "Arial", "font_size": 16, "primary_color": "&H00FFFFFF", "outline_color": "&H00000000", "back_color": "&H80000000", "bold": 0, "alignment": 8, "description": "字幕显示在画面顶部"},
    {"id": 13, "name": "右侧对齐", "font": "Arial", "font_size": 16, "primary_color": "&H00FFFFFF", "outline_color": "&H00000000", "back_color": "&H80000000", "bold": 0, "alignment": 3, "description": "底部右侧对齐"},
    {"id": 14, "name": "霓虹效果", "font": "Arial", "font_size": 18, "primary_color": "&H0000FFFF", "outline_color": "&H00FF00FF", "back_color": "&H00000000", "bold": 0, "alignment": 2, "description": "霓虹光效，轮廓发光"},
    {"id": 15, "name": "阴影增强", "font": "Arial", "font_size": 18, "primary_color": "&H00FFFFFF", "outline_color": "&H00000000", "back_color": "&H00000000", "bold": 0, "alignment": 2, "description": "深层阴影，立体感强"},
    {"id": 16, "name": "圆角背景", "font": "Arial", "font_size": 18, "primary_color": "&H00FFFFFF", "outline_color": "&H00000000", "back_color": "&HCC000000", "bold": 0, "alignment": 2, "description": "圆角矩形黑底衬"},
    {"id": 17, "name": "双色渐变", "font": "Arial", "font_size": 18, "primary_color": "&H00FF88FF", "outline_color": "&H008800FF", "back_color": "&H80000000", "bold": 0, "alignment": 2, "description": "粉紫渐变效果"},
    {"id": 18, "name": "无框极简", "font": "Arial", "font_size": 16, "primary_color": "&H00FFFFFF", "outline_color": "&H00000000", "back_color": "&H00000000", "bold": 0, "alignment": 2, "description": "无边框，极简风格"},
    {"id": 19, "name": "青涩少年", "font": "Microsoft YaHei", "font_size": 18, "primary_color": "&H00CCFF88", "outline_color": "&H00336633", "back_color": "&H80000000", "bold": 0, "alignment": 2, "description": "青绿色，清新少年感"},
    {"id": 20, "name": "影院字幕", "font": "Arial", "font_size": 22, "primary_color": "&H00FFFFFF", "outline_color": "&H00000000", "back_color": "&H00000000", "bold": 0, "alignment": 8, "description": "顶部影院式字幕"},
]

# 建立 id → style 快速查找
STYLE_MAP = {s["id"]: s for s in SUBTITLE_STYLES}

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
            quota_seconds INTEGER NOT NULL DEFAULT 300,
            total_used_seconds INTEGER NOT NULL DEFAULT 0,
            is_premium INTEGER NOT NULL DEFAULT 0,
            membership_tier TEXT NOT NULL DEFAULT 'free',
            membership_expires_at DATETIME,
            last_monthly_refresh DATETIME,
            carryover_seconds INTEGER NOT NULL DEFAULT 0,
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
            style_id INTEGER,
            error_message TEXT,
            duration_seconds INTEGER,
            expires_at DATETIME,
            created_at DATETIME DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            type TEXT NOT NULL CHECK(type IN ('topup','membership')),
            package_key TEXT,
            membership_tier TEXT,
            seconds_added INTEGER DEFAULT 0,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','paid','expired','failed')),
            created_at DATETIME DEFAULT (datetime('now')),
            paid_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            expires_at DATETIME NOT NULL,
            created_at DATETIME DEFAULT (datetime('now'))
        );
    """)
    conn.commit()

    # 迁移：为旧表增加缺失列
    migrations = [
        ("users", "quota_seconds", "ALTER TABLE users ADD COLUMN quota_seconds INTEGER NOT NULL DEFAULT 300"),
        ("users", "total_used_seconds", "ALTER TABLE users ADD COLUMN total_used_seconds INTEGER NOT NULL DEFAULT 0"),
        ("users", "is_premium", "ALTER TABLE users ADD COLUMN is_premium INTEGER NOT NULL DEFAULT 0"),
        ("users", "membership_tier", "ALTER TABLE users ADD COLUMN membership_tier TEXT NOT NULL DEFAULT 'free'"),
        ("users", "membership_expires_at", "ALTER TABLE users ADD COLUMN membership_expires_at DATETIME"),
        ("users", "last_monthly_refresh", "ALTER TABLE users ADD COLUMN last_monthly_refresh DATETIME"),
        ("users", "carryover_seconds", "ALTER TABLE users ADD COLUMN carryover_seconds INTEGER NOT NULL DEFAULT 0"),
        ("tasks", "duration_seconds", "ALTER TABLE tasks ADD COLUMN duration_seconds INTEGER"),
        ("tasks", "expires_at", "ALTER TABLE tasks ADD COLUMN expires_at DATETIME"),
        ("tasks", "style_id", "ALTER TABLE tasks ADD COLUMN style_id INTEGER"),
    ]
    for table, col, sql in migrations:
        cur = conn.execute(f"PRAGMA table_info({table})")
        existing = {r[1] for r in cur.fetchall()}
        if col not in existing:
            conn.execute(sql)
            logger.info("迁移: %s 表增加 %s 列", table, col)
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
    style_id: int | None = None

class SrtEditRequest(BaseModel):
    srt_content: str

class TopupOrderRequest(BaseModel):
    user_id: int
    package_key: str

class MembershipOrderRequest(BaseModel):
    user_id: int
    tier: str

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def get_video_duration_ffprobe(video_path: str) -> int | None:
    try:
        cmd = [FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return int(float(result.stdout.strip()))
    except Exception as e:
        logger.warning("ffprobe 获取时长失败: %s", e)
    return None


def issue_session(conn, user_id: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(days=SESSION_TTL_DAYS)).isoformat()
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires_at),
    )
    return token, expires_at


def _parse_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()


def _load_user_from_token(token: str | None) -> dict:
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT u.*
               FROM sessions s
               JOIN users u ON u.id = s.user_id
               WHERE s.token=? AND s.expires_at > ?""",
            (token, datetime.now().isoformat()),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="登录已失效")
        return dict(row)
    finally:
        conn.close()


async def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    return _load_user_from_token(_parse_bearer_token(authorization))


async def get_current_user_for_download(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict:
    return _load_user_from_token(_parse_bearer_token(authorization) or token)


def require_same_user(current_user: dict, user_id: int):
    if current_user["id"] != user_id:
        raise HTTPException(status_code=403, detail="无权访问该用户")


def require_task_owner(current_user: dict, task_row):
    if task_row["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="无权访问该任务")


def cleanup_expired_sessions():
    conn = get_db()
    try:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (datetime.now().isoformat(),))
        conn.commit()
    finally:
        conn.close()

_SRT_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*$")


def _srt_time_to_ass(value: str) -> str:
    match = _SRT_TIME_RE.match(value)
    if not match:
        raise ValueError(f"invalid SRT timestamp: {value}")
    hour, minute, second, millis = match.groups()
    centisecond = int(millis.ljust(3, "0")[:3]) // 10
    return f"{int(hour)}:{int(minute):02d}:{int(second):02d}.{centisecond:02d}"


def _ass_escape_text(value: str) -> str:
    value = value.replace("\\", "\\\\").replace("{", r"\{").replace("}", r"\}")
    return value.replace("\n", r"\N")


REFERENCE_HEIGHT = 720  # 样式 font_size 的参考高度


def _get_video_resolution(video_path: str) -> tuple[int, int]:
    """用 ffprobe 获取视频分辨率"""
    try:
        cmd = [FFPROBE_PATH, "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            parts = r.stdout.strip().split(",")
            return int(parts[0]), int(parts[1])
    except Exception as e:
        logger.warning("获取视频分辨率失败: %s", e)
    return 1920, 1080


def srt_to_ass(srt_text: str, style_id: int = 1, video_width: int = 1280, video_height: int = 720) -> str:
    """将 SRT 内容转换为 ASS 格式，应用指定样式，字体大小适配视频分辨率"""
    style = STYLE_MAP.get(style_id, STYLE_MAP[1])
    font_name = style["font"]
    # 根据视频实际高度缩放字体大小（参考 720p）
    scale = max(0.5, video_height / REFERENCE_HEIGHT)
    font_size = max(12, int(style["font_size"] * scale))
    primary = style["primary_color"]
    outline = style["outline_color"]
    back = style["back_color"]
    bold = style["bold"]
    alignment = style["alignment"]

    normalized = srt_text.strip().replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", normalized)
    ass_events = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue

        if "-->" in lines[0]:
            time_line = lines[0]
            text_lines = lines[1:]
        elif len(lines) >= 3 and "-->" in lines[1]:
            time_line = lines[1]
            text_lines = lines[2:]
        else:
            continue

        try:
            start, end = [part.strip() for part in time_line.split("-->", 1)]
            text = _ass_escape_text("\n".join(text_lines))
            ass_events.append(
                f"Dialogue: 0,{_srt_time_to_ass(start)},{_srt_time_to_ass(end)},Default,,0,0,0,,{text}"
            )
        except (IndexError, ValueError) as e:
            logger.warning("跳过无法转换的 SRT 字幕块: %s", e)

    if not ass_events:
        raise ValueError("SRT 中没有可转换的字幕时间轴")

    # 用视频实际分辨率作为 PlayRes（ASS 字体/坐标直接对应视频像素）
    play_res_x = video_width
    play_res_y = video_height
    margin = max(12, int(20 * video_height / REFERENCE_HEIGHT))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary},&H000000FF,{outline},{back},{bold},0,0,0,100,100,0,0,1,2,1,{alignment},{margin},{margin},{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header + "\n".join(ass_events)


def _ffmpeg_filter_path(subtitle_path: Path) -> str:
    path = subtitle_path.resolve().as_posix()
    return path.replace(":", "\\:").replace("'", "\\'")


def ffmpeg_subtitles_filter(subtitle_path: Path) -> str:
    return f"subtitles='{_ffmpeg_filter_path(subtitle_path)}'"


def ffmpeg_ass_filter(subtitle_path: Path) -> str:
    return f"ass='{_ffmpeg_filter_path(subtitle_path)}'"


def _setup_fontconfig_env() -> dict | None:
    """Windows 上配置 fontconfig，让 libass 能找到系统字体渲染字幕"""
    if sys.platform != "win32":
        return None

    font_dir = "C:/Windows/Fonts"
    if not os.path.isdir(font_dir):
        logger.warning("Windows 字体目录不存在: %s", font_dir)
        return None

    conf_dir = OUTPUT_DIR / ".fontconfig"
    conf_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = conf_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    conf_path = conf_dir / "fonts.conf"
    if not conf_path.exists():
        conf_path.write_text(
            '<?xml version="1.0"?>\n'
            '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
            "<fontconfig>\n"
            "  <dir>C:/Windows/Fonts</dir>\n"
            f"  <cachedir>{cache_dir.as_posix()}</cachedir>\n"
            "</fontconfig>\n",
            encoding="utf-8",
        )

    env = os.environ.copy()
    env["FONTCONFIG_PATH"] = str(conf_dir)
    return env


def build_ffmpeg_burn_cmd(video_path: Path, vf: str, output_path: Path) -> list[str]:
    return [
        FFMPEG_PATH,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        vf,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def try_refresh_monthly_quota(conn, user: dict) -> dict:
    """检查并刷新月度配额（含高级会员配额结转逻辑）"""
    tier = user["membership_tier"]
    if tier == "free":
        return dict(user)

    config = MEMBERSHIP_CONFIG.get(tier)
    if not config:
        return dict(user)

    # 检查会员是否过期
    expires_at = user.get("membership_expires_at")
    if expires_at:
        try:
            exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00").replace("+00:00", ""))
            if exp < datetime.now():
                conn.execute(
                    "UPDATE users SET membership_tier='free', is_premium=0, carryover_seconds=0, quota_seconds=? WHERE id=?",
                    (MEMBERSHIP_CONFIG["free"]["initial_quota"], user["id"]),
                )
                conn.commit()
                return dict(conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())
        except (ValueError, TypeError):
            pass

    # 检查是否需要月度刷新
    last_refresh = user.get("last_monthly_refresh")
    now = datetime.now()
    should_refresh = False
    if not last_refresh:
        should_refresh = True
    else:
        try:
            lr = datetime.fromisoformat(str(last_refresh).replace("Z", "+00:00").replace("+00:00", ""))
            if (now - lr).days >= 30:
                should_refresh = True
        except (ValueError, TypeError):
            should_refresh = True

    if should_refresh:
        monthly = config["monthly_quota"]
        carryover = config["carryover_months"]

        if carryover > 0 and tier == "premium":
            # 高级会员：配额结转逻辑
            # last_carryover = 上次结转进本月的量
            last_carryover = user.get("carryover_seconds", 0)
            remaining = user["quota_seconds"]
            # 本月剩余中，来自"新鲜配额"的部分
            fresh_remaining = max(0, remaining - last_carryover)
            # 可结转到下个月的部分 = 本月新鲜剩余的，上限为一月配额
            next_carryover = min(monthly, fresh_remaining)
            # 新配额 = 新鲜月配额 + 上次结转到本月的（尚未用完则并入）
            new_quota = monthly + max(0, remaining)  # remaining 中已含未用完的 last_carryover
            conn.execute(
                "UPDATE users SET quota_seconds=?, carryover_seconds=?, last_monthly_refresh=? WHERE id=?",
                (new_quota, next_carryover, now.isoformat(), user["id"]),
            )
            logger.info("高级会员配额刷新: user=%s remaining=%s last_carryover=%s next_carryover=%s new_quota=%s",
                        user["id"], remaining, last_carryover, next_carryover, new_quota)
        else:
            # 专业会员 / 普通：直接重置
            conn.execute(
                "UPDATE users SET quota_seconds=?, carryover_seconds=0, last_monthly_refresh=? WHERE id=?",
                (monthly, now.isoformat(), user["id"]),
            )
            logger.info("月度配额刷新: user=%s tier=%s quota=%s", user["id"], tier, monthly)

        conn.commit()
        updated = dict(conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())
        return updated

    return dict(user)


def cleanup_expired_tasks():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, video_path, output_video_path FROM tasks WHERE expires_at IS NOT NULL AND expires_at <= datetime('now')"
        ).fetchall()
        for row in rows:
            for attr in ["video_path", "output_video_path"]:
                fp = row[attr]
                if fp and Path(fp).exists():
                    Path(fp).unlink(missing_ok=True)
            conn.execute("DELETE FROM tasks WHERE id=?", (row["id"],))
            logger.info("清理过期任务: id=%s", row["id"])
        conn.commit()
    except Exception as e:
        logger.error("清理过期任务失败: %s", e)
    finally:
        conn.close()

def set_task_expiry(task_id: str, user_id: int):
    conn = get_db()
    try:
        row = conn.execute("SELECT membership_tier FROM users WHERE id=?", (user_id,)).fetchone()
        tier = row["membership_tier"] if row else "free"
        config = MEMBERSHIP_CONFIG.get(tier, MEMBERSHIP_CONFIG["free"])
        expires_at = (datetime.now() + timedelta(days=config["retention_days"])).isoformat()
        conn.execute("UPDATE tasks SET expires_at=? WHERE id=?", (expires_at, task_id))
        conn.commit()
    except Exception as e:
        logger.error("设置任务过期失败: %s", e)
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# 应用生命周期
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("数据库初始化/迁移完成")
    cleanup_expired_tasks()
    cleanup_expired_sessions()
    yield

app = FastAPI(title="智影字幕 API", version="3.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static", html=True), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = Path("static") / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>智影字幕</h1><p>前端页面未找到</p>")


# ================================ API 路由 ================================

# --- 登录 ---

@app.post("/send-code")
async def send_code(body: SendCodeRequest):
    if os.getenv("ENV") == "production":
        raise HTTPException(status_code=501, detail="生产环境未配置短信验证码服务")
    logger.info("Mock 发送验证码: phone=%s", body.phone)
    return {"message": "mock code 123456"}

@app.post("/login")
async def login(body: LoginRequest):
    if os.getenv("ENV") == "production":
        raise HTTPException(status_code=501, detail="生产环境未配置短信验证码服务")
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
            cur = conn.execute(
                "INSERT INTO users (phone, quota_seconds) VALUES (?, ?)",
                (body.phone, MEMBERSHIP_CONFIG["free"]["initial_quota"]),
            )
            conn.commit()
            user_id = cur.lastrowid
            logger.info("新用户注册: id=%d phone=%s", user_id, body.phone)
        token, expires_at = issue_session(conn, user_id)
        conn.commit()
        return {"user_id": user_id, "access_token": token, "expires_at": expires_at, "message": "ok"}
    finally:
        conn.close()


# --- 用户信息 ---

@app.get("/user/{user_id}/profile")
async def get_user_profile(user_id: int, current_user: dict = Depends(get_current_user)):
    require_same_user(current_user, user_id)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        user = dict(row)
        user = try_refresh_monthly_quota(conn, user)

        stats = conn.execute(
            "SELECT COUNT(*) as total, SUM(duration_seconds) as total_duration FROM tasks WHERE user_id=? AND status='done'",
            (user_id,),
        ).fetchone()

        tier = user["membership_tier"]
        config = MEMBERSHIP_CONFIG.get(tier, MEMBERSHIP_CONFIG["free"])

        is_active = True
        if tier != "free" and user["membership_expires_at"]:
            try:
                exp = datetime.fromisoformat(str(user["membership_expires_at"]).replace("Z", "+00:00").replace("+00:00", ""))
                if exp < datetime.now():
                    is_active = False
            except (ValueError, TypeError):
                is_active = False

        return {
            "user_id": user["id"],
            "phone": user["phone"],
            "quota_seconds": user["quota_seconds"],
            "total_used_seconds": user["total_used_seconds"],
            "is_premium": bool(user["is_premium"]),
            "membership_tier": user["membership_tier"],
            "membership_tier_name": config["name"],
            "membership_expires_at": user["membership_expires_at"],
            "membership_active": is_active,
            "can_burn": config["can_burn"],
            "can_edit_subtitles": config["can_edit_subtitles"],
            "high_precision": config["high_precision"],
            "can_custom_style": config["can_custom_style"],
            "carryover_months": config["carryover_months"],
            "max_task_duration": config["max_task_duration"],
            "monthly_quota": config["monthly_quota"] if is_active else 0,
            "retention_days": config["retention_days"],
            "total_tasks": stats["total"] or 0,
            "total_duration": stats["total_duration"] or 0,
        }
    finally:
        conn.close()


# --- 上传（含配额检查和时长限制） ---

@app.post("/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    user_id: int = Form(...),
    current_user: dict = Depends(get_current_user),
):
    require_same_user(current_user, user_id)
    task_id = str(uuid.uuid4())
    ext = Path(video.filename).suffix.lower() if video.filename else ".mp4"
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持的视频格式")
    if video.content_type and not video.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="请上传视频文件")
    video_path = UPLOAD_DIR / f"{task_id}{ext}"

    size = 0
    try:
        with video_path.open("wb") as f:
            while chunk := await video.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    video_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="视频文件超过大小限制")
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("写入上传文件失败: %s", e)
        video_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="上传失败")

    duration = get_video_duration_ffprobe(str(video_path))
    if duration is None or duration <= 0:
        video_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="无法识别视频时长")

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT quota_seconds, membership_tier, membership_expires_at, carryover_seconds FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        if not row:
            video_path.unlink(missing_ok=True)
            raise HTTPException(status_code=404, detail="用户不存在")

        tier = row["membership_tier"]
        config = MEMBERSHIP_CONFIG.get(tier, MEMBERSHIP_CONFIG["free"])

        # 检查单个任务最大时长
        max_dur = config["max_task_duration"]
        if duration and duration > max_dur:
            video_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"视频时长超过限制：当前套餐最大支持 {max_dur} 秒/任务（视频时长 {duration} 秒）。",
            )

        # 检查配额
        if tier != "premium" and row["quota_seconds"] < duration:
            video_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"配额不足：需要 {duration} 秒，剩余 {row['quota_seconds']} 秒。请购买增量包或升级会员。",
            )

        # 创建任务
        conn.execute(
            "INSERT INTO tasks (id, user_id, status, video_path, duration_seconds) VALUES (?, ?, 'pending', ?, ?)",
            (task_id, user_id, str(video_path), duration),
        )

        # 预扣配额
        should_refund = False
        if duration and duration > 0:
            if tier == "premium":
                # premium 不预扣（不限制配额）
                pass
            else:
                new_quota = max(0, row["quota_seconds"] - duration)
                conn.execute("UPDATE users SET quota_seconds=? WHERE id=?", (new_quota, user_id))
                should_refund = True

        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("上传失败: %s", e)
        raise HTTPException(status_code=500, detail="上传失败")
    finally:
        conn.close()

    background_tasks.add_task(
        process_whisper, task_id, str(video_path), user_id,
        should_refund_on_fail=should_refund,
    )

    return {"task_id": task_id}


# --- 任务状态 ---

@app.get("/task/{task_id}")
async def get_task(task_id: str, current_user: dict = Depends(get_current_user)):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    require_task_owner(current_user, row)
    result = {
        "status": row["status"],
        "srt_content": row["srt_content"],
        "duration_seconds": row["duration_seconds"],
        "style_id": row["style_id"],
    }
    if row["output_video_path"]:
        result["output_video_url"] = f"/download/video/{task_id}"
    if row["error_message"]:
        result["error_message"] = row["error_message"]
    return result


# --- 字幕编辑（专业/高级会员） ---

@app.put("/task/{task_id}/srt")
async def edit_srt(task_id: str, body: SrtEditRequest, current_user: dict = Depends(get_current_user)):
    """编辑任务字幕内容。需要专业会员或以上。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT t.*, u.membership_tier FROM tasks t JOIN users u ON t.user_id = u.id WHERE t.id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        require_task_owner(current_user, row)
        tier = row["membership_tier"]
        config = MEMBERSHIP_CONFIG.get(tier, MEMBERSHIP_CONFIG["free"])
        if not config["can_edit_subtitles"]:
            raise HTTPException(status_code=403, detail="当前套餐不支持编辑字幕")

        conn.execute("UPDATE tasks SET srt_content=? WHERE id=?", (body.srt_content, task_id))
        conn.commit()
        return {"message": "ok"}
    finally:
        conn.close()


# --- 历史任务 ---

@app.get("/user/{user_id}/tasks")
async def get_user_tasks(user_id: int, current_user: dict = Depends(get_current_user)):
    require_same_user(current_user, user_id)
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT id, status, duration_seconds, expires_at, created_at, style_id,
                      srt_content IS NOT NULL AND srt_content != '' as has_srt,
                      output_video_path IS NOT NULL AND output_video_path != '' as has_video
               FROM tasks WHERE user_id=? ORDER BY created_at DESC LIMIT 50""",
            (user_id,),
        ).fetchall()
        cleanup_expired_tasks()
        return {"tasks": [{
            "task_id": r["id"],
            "status": r["status"],
            "duration_seconds": r["duration_seconds"],
            "expires_at": r["expires_at"],
            "created_at": r["created_at"],
            "has_srt": bool(r["has_srt"]),
            "has_video": bool(r["has_video"]),
            "style_id": r["style_id"],
        } for r in rows]}
    finally:
        conn.close()


# --- 下载 ---

@app.get("/download/srt/{task_id}")
async def download_srt(task_id: str, current_user: dict = Depends(get_current_user_for_download)):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        require_task_owner(current_user, row)
        if not row["srt_content"]:
            raise HTTPException(status_code=400, detail="字幕内容为空")
        _check_expired(row)
        srt_path = OUTPUT_DIR / f"{task_id}.srt"
        srt_path.write_text(row["srt_content"], encoding="utf-8")
        return FileResponse(str(srt_path), media_type="text/plain",
                            filename=f"zhiying_{task_id[:8]}.srt")
    finally:
        conn.close()

@app.get("/download/video/{task_id}")
async def download_video(task_id: str, current_user: dict = Depends(get_current_user_for_download)):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        require_task_owner(current_user, row)
        if not row["output_video_path"]:
            raise HTTPException(status_code=400, detail="视频尚未生成")
        _check_expired(row)
        video_path = Path(row["output_video_path"])
        if not video_path.exists():
            raise HTTPException(status_code=404, detail="视频文件不存在")
        return FileResponse(str(video_path), media_type="video/mp4",
                            filename=f"zhiying_{task_id[:8]}_sub.mp4")
    finally:
        conn.close()

def _check_expired(row):
    if row["expires_at"]:
        try:
            exp = datetime.fromisoformat(str(row["expires_at"]))
            if exp < datetime.now():
                raise HTTPException(status_code=410, detail="该资源已过期")
        except (ValueError, TypeError):
            pass


# --- 字幕样式 ---

@app.get("/styles")
async def get_styles():
    """获取所有字幕样式列表"""
    return {"styles": [
        {"id": s["id"], "name": s["name"], "description": s["description"],
         "font": s["font"], "font_size": s["font_size"], "bold": bool(s["bold"]),
         "alignment": s["alignment"], "primary_color": s["primary_color"]}
        for s in SUBTITLE_STYLES
    ]}


# --- FFmpeg 诊断 ---

@app.get("/check-ffmpeg")
async def check_ffmpeg():
    """检查 FFmpeg 是否可用以及支持的滤镜"""
    result = {"available": False, "path": None, "version": None, "has_ass_filter": False, "has_subtitles_filter": False}
    try:
        r = subprocess.run([FFMPEG_PATH, "-version"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            result["available"] = True
            result["version"] = r.stdout.split("\n")[0] if r.stdout else "unknown"
    except Exception as e:
        result["error"] = str(e)
        return result

    try:
        r2 = subprocess.run([FFMPEG_PATH, "-filters"], capture_output=True, text=True, timeout=10)
        filters = r2.stdout
        result["has_ass_filter"] = "ass" in filters
        result["has_subtitles_filter"] = "subtitles" in filters
    except Exception as e:
        result["filter_error"] = str(e)

    return result


# --- 烧录（支持样式选择） ---

@app.post("/burn")
async def burn_subtitles(body: BurnRequest, current_user: dict = Depends(get_current_user)):
    """FFmpeg 烧录字幕。优先 subtitles+SRT（稳健），失败时尝试 ASS（样式）。"""
    # 顶层防护：确保任何未预期异常都返回 JSON
    try:
        return await _do_burn(body, current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("烧录未知异常: %s", e)
        raise HTTPException(status_code=500, detail=f"烧录失败: {str(e)[:200]}")


async def _do_burn(body: BurnRequest, current_user: dict):
    conn = get_db()
    try:
        task_row = conn.execute(
            "SELECT t.*, u.membership_tier FROM tasks t JOIN users u ON t.user_id = u.id WHERE t.id = ?",
            (body.task_id,),
        ).fetchone()
    finally:
        conn.close()

    if not task_row:
        raise HTTPException(status_code=404, detail="任务不存在")
    require_task_owner(current_user, task_row)
    if not task_row["srt_content"]:
        raise HTTPException(status_code=400, detail="字幕内容为空")

    tier = task_row["membership_tier"]
    config = MEMBERSHIP_CONFIG.get(tier, MEMBERSHIP_CONFIG["free"])
    if not config["can_burn"]:
        raise HTTPException(status_code=403, detail="当前套餐不支持烧录")

    style_id = body.style_id or 1
    if style_id != 1 and not config.get("can_custom_style"):
        raise HTTPException(status_code=403, detail="当前套餐不支持自定义样式")

    if not task_row["video_path"]:
        raise HTTPException(status_code=400, detail="原始视频路径丢失")
    video_path = Path(task_row["video_path"])
    if not video_path.exists():
        raise HTTPException(status_code=400, detail="原始视频文件不存在")

    output_path = OUTPUT_DIR / f"{body.task_id}_sub.mp4"
    srt_path = OUTPUT_DIR / f"{body.task_id}.srt"
    ass_path = OUTPUT_DIR / f"{body.task_id}.ass"
    srt_path.write_text(task_row["srt_content"], encoding="utf-8")

    # 检测视频分辨率，用于自适应字幕大小
    vw, vh = _get_video_resolution(str(video_path))
    logger.info("视频分辨率: %dx%d, 字幕将适配字体大小", vw, vh)

    # Windows 上配置 fontconfig，让 libass 能找到系统字体
    fc_env = _setup_fontconfig_env()
    subprocess_kwargs = dict(capture_output=True, text=True, timeout=300)
    if fc_env:
        subprocess_kwargs["env"] = fc_env

    # 优先级：先尝试 ASS（含样式），回退 SRT+subtitles
    ass_ok = False
    if style_id != 1 or tier == "premium":
        try:
            ass_content = srt_to_ass(task_row["srt_content"], style_id, vw, vh)
            ass_path.write_text(ass_content, encoding="utf-8")
            cmd = build_ffmpeg_burn_cmd(video_path, ffmpeg_ass_filter(ass_path), output_path)
            logger.info("FFmpeg ASS 烧录: task=%s style=%s vh=%d", body.task_id, style_id, vh)
            r = subprocess.run(cmd, **subprocess_kwargs)
            if r.returncode == 0:
                ass_ok = True
            else:
                logger.warning("ASS 失败，将回退: %s", r.stderr[:500])
        except Exception as e:
            logger.warning("ASS 异常，将回退: %s", e)

    if not ass_ok:
        cmd2 = build_ffmpeg_burn_cmd(video_path, ffmpeg_subtitles_filter(srt_path), output_path)
        logger.info("FFmpeg subtitles 烧录: task=%s", body.task_id)
        try:
            r2 = subprocess.run(cmd2, **subprocess_kwargs)
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="FFmpeg 未安装，请安装 FFmpeg")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"FFmpeg 执行失败: {str(e)[:200]}")

        if r2.returncode != 0:
            err = r2.stderr[:300] if r2.stderr else "未知错误"
            raise HTTPException(status_code=500, detail=f"烧录失败: {err}")

    _upd_burn(body.task_id, str(output_path), style_id)
    return {"output_video_url": f"/download/video/{body.task_id}"}


def _upd_burn(tid, p, sid):
    conn = get_db()
    try:
        conn.execute("UPDATE tasks SET output_video_path=?, style_id=? WHERE id=?", (p, sid, tid))
        conn.commit()
    except Exception as e:
        logger.error("更新烧录结果失败: %s", e)
    finally:
        conn.close()


# --- Mock 支付 ---

@app.post("/create-topup-order")
async def create_topup_order(body: TopupOrderRequest, current_user: dict = Depends(get_current_user)):
    require_same_user(current_user, body.user_id)
    pkg = TOPUP_PACKAGES.get(body.package_key)
    if not pkg:
        raise HTTPException(status_code=400, detail="无效的增量包")
    order_id = str(uuid.uuid4())
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO orders (id, user_id, type, package_key, seconds_added, amount, status) VALUES (?, ?, 'topup', ?, ?, ?, 'pending')",
            (order_id, body.user_id, body.package_key, pkg["seconds"], pkg["price"]),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("增量包订单创建: order=%s user=%s pkg=%s", order_id, body.user_id, body.package_key)
    return {"order_id": order_id, "package_name": pkg["name"], "seconds": pkg["seconds"],
            "amount": pkg["price"], "mock_pay_url": f"/mock-pay?order_id={order_id}&type=topup"}

@app.post("/create-membership-order")
async def create_membership_order(body: MembershipOrderRequest, current_user: dict = Depends(get_current_user)):
    require_same_user(current_user, body.user_id)
    config = MEMBERSHIP_CONFIG.get(body.tier)
    if not config or body.tier == "free":
        raise HTTPException(status_code=400, detail="无效的会员等级")
    order_id = str(uuid.uuid4())
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO orders (id, user_id, type, membership_tier, amount, status) VALUES (?, ?, 'membership', ?, ?, 'pending')",
            (order_id, body.user_id, body.tier, config["price"]),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("会员订单创建: order=%s user=%s tier=%s", order_id, body.user_id, body.tier)
    return {"order_id": order_id, "tier": body.tier, "tier_name": config["name"],
            "amount": config["price"], "mock_pay_url": f"/mock-pay?order_id={order_id}&type=membership"}

@app.post("/mock-pay/{order_id}")
async def mock_pay(order_id: str, current_user: dict = Depends(get_current_user)):
    if os.getenv("ENV") == "production":
        raise HTTPException(status_code=403, detail="生产环境不允许 Mock 支付")
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="订单不存在")
        if row["status"] != "pending":
            raise HTTPException(status_code=400, detail="订单已处理")
        order = dict(row)
        require_same_user(current_user, order["user_id"])

        if order["type"] == "topup":
            conn.execute(
                "UPDATE users SET quota_seconds = quota_seconds + ? WHERE id=?",
                (order["seconds_added"], order["user_id"]),
            )
            logger.info("增量包发货: user=%s seconds=%s", order["user_id"], order["seconds_added"])

        elif order["type"] == "membership":
            tier = order["membership_tier"]
            cfg = MEMBERSHIP_CONFIG.get(tier, {})
            expires_at = (datetime.now() + timedelta(days=30)).isoformat()
            # 开通会员：重置配额为当月配额（含初始结转）
            conn.execute(
                """UPDATE users SET
                    membership_tier=?, is_premium=1,
                    quota_seconds=MAX(quota_seconds, ?),
                    carryover_seconds=0,
                    membership_expires_at=?,
                    last_monthly_refresh=?
                 WHERE id=?""",
                (tier, cfg.get("monthly_quota", 0), expires_at, datetime.now().isoformat(), order["user_id"]),
            )
            logger.info("会员开通: user=%s tier=%s expires=%s", order["user_id"], tier, expires_at)

        conn.execute("UPDATE orders SET status='paid', paid_at=datetime('now') WHERE id=?", (order_id,))
        conn.commit()
        return {"message": "支付成功", "type": order["type"]}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("Mock 支付处理失败: %s", e)
        raise HTTPException(status_code=500, detail="支付处理失败")
    finally:
        conn.close()


@app.get("/packages")
async def get_packages():
    return {
        "topup_packages": {k: {"name": v["name"], "seconds": v["seconds"], "price": v["price"]}
                           for k, v in TOPUP_PACKAGES.items()},
        "membership_plans": {k: {
            "name": v["name"], "monthly_quota": v["monthly_quota"],
            "can_burn": v["can_burn"], "can_edit_subtitles": v["can_edit_subtitles"],
            "high_precision": v["high_precision"], "can_custom_style": v["can_custom_style"],
            "carryover_months": v["carryover_months"],
            "max_task_duration": v["max_task_duration"],
            "price": v["price"], "retention_days": v["retention_days"],
        } for k, v in MEMBERSHIP_CONFIG.items()},
    }

@app.get("/health")
async def health():
    return {"status": "ok"}


# ============================== 后台任务 ==============================

def process_whisper(task_id: str, video_path: str, user_id: int, should_refund_on_fail: bool = False):
    conn = get_db()
    try:
        conn.execute("UPDATE tasks SET status='processing' WHERE id=?", (task_id,))
        conn.commit()

        api_key = os.getenv("WHISPER_API_KEY")
        base_url = os.getenv("WHISPER_BASE_URL")
        headers = {"Authorization": f"Bearer {api_key}"}
        data = {"model": "whisper-1", "response_format": "srt"}

        logger.info("Whisper 请求开始: task=%s", task_id)
        with open(video_path, "rb") as f, httpx.Client(timeout=120) as client:
            files = {"file": (f"{task_id}.mp4", f, "video/mp4")}
            resp = client.post(f"{base_url}/audio/transcriptions", headers=headers, files=files, data=data)

        if resp.status_code != 200:
            raise RuntimeError(f"Whisper API 返回 {resp.status_code}: {resp.text[:300]}")

        srt_text = resp.text.strip()
        logger.info("Whisper 完成: task=%s 长度=%d 字符", task_id, len(srt_text))

        conn.execute("UPDATE tasks SET status='done', srt_content=? WHERE id=?", (srt_text, task_id))
        conn.commit()

        # 累计使用时长
        row = conn.execute("SELECT duration_seconds FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row and row["duration_seconds"]:
            conn.execute("UPDATE users SET total_used_seconds = total_used_seconds + ? WHERE id=?",
                         (row["duration_seconds"], user_id))
            conn.commit()

        set_task_expiry(task_id, user_id)

    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Whisper 失败: task=%s error=%s", task_id, tb)
        conn.execute("UPDATE tasks SET status='failed', error_message=? WHERE id=?", ("转写失败，请稍后重试", task_id))
        conn.commit()
        if should_refund_on_fail:
            row = conn.execute("SELECT duration_seconds FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row and row["duration_seconds"]:
                conn.execute("UPDATE users SET quota_seconds = quota_seconds + ? WHERE id=?",
                             (row["duration_seconds"], user_id))
                conn.commit()
                logger.info("配额退还: user=%s seconds=%s", user_id, row["duration_seconds"])
        set_task_expiry(task_id, user_id)
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
        reload_excludes=["data/", "uploads/", "output/", "logs/", ".env", "*.db", "*.db-*", "*.pyc", "__pycache__/"],
    )
