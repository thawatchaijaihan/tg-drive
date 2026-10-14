#!/usr/bin/env python3
"""
GAPT-CINEMA — Pipeline Worker Daemon
Runs on OCI server alongside stream_server.py.

Responsibilities:
  1. Poll the Telegram channel for new video uploads (via Telethon event handler)
  2. Queue videos that need AV1 optimization (size > 2GB or not yet AV1)
  3. Dispatch Google Colab CLI transcoding jobs
  4. Monitor job completion and parse results
  5. Update the GAPT-CINEMA database (tg_stream.db) with new msg_id
  6. Auto-purge temporary cache files from SSD

Architecture:
  - Runs as systemd service: gapt-pipeline.service
  - Shares .env credentials with tg-filestream.service
  - Communicates with Colab via `colab-cli` (headless)

Fallback: If Colab CLI is unavailable (quota/network), queues are preserved
         and retried on next cycle.
"""

import os
import re
import sys
import json
import time
import sqlite3
import asyncio
import logging
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, timezone

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/home/ubuntu/tg-filestream/pipeline.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("gapt-pipeline")

# ─── Configuration ───────────────────────────────────────────────────────────
BASE_DIR = Path(os.environ.get("BASE_DIR", "/home/ubuntu/tg-filestream"))

# Load .env
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SESSION_PATH = os.environ.get("PIPELINE_SESSION", str(BASE_DIR / "pipeline_bot.session"))

DB_PATH = BASE_DIR / "tg_stream.db"
QUEUE_DB_PATH = BASE_DIR / "pipeline_queue.db"
COLAB_SCRIPT = BASE_DIR / "colab_av1_encoder.py"
CACHE_DIR = BASE_DIR / "cache"

# Size threshold: videos above this size need AV1 re-encoding
SIZE_THRESHOLD_BYTES = 1_950 * 1024 * 1024  # 1.95 GB

# Polling interval between queue checks
POLL_INTERVAL_SECS = 30

# Max concurrent Colab jobs (free tier = 1)
MAX_CONCURRENT_JOBS = 1

# ─── Pipeline Queue Database ────────────────────────────────────────────────
def init_queue_db():
    """Initialize the pipeline queue database."""
    conn = sqlite3.connect(QUEUE_DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pipeline_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        msg_id INTEGER NOT NULL,
        file_name TEXT,
        file_size INTEGER DEFAULT 0,
        duration REAL DEFAULT 0,
        status TEXT DEFAULT 'pending',
        colab_job_id TEXT,
        new_msg_id INTEGER,
        error_msg TEXT,
        retry_count INTEGER DEFAULT 0,
        created_at REAL,
        updated_at REAL,
        UNIQUE(chat_id, msg_id)
    )
    """)
    conn.commit()
    conn.close()
    logger.info("Pipeline queue database initialized.")


def normalize_channel_id(cid: int) -> int:
    """Ensure channel ID has -100 prefix required by Telethon/Telegram bot API."""
    if cid > 0:
        return -int(f"100{cid}")
    return cid


def add_to_queue(chat_id: int, msg_id: int, file_name: str, file_size: int, duration: float = 0):
    """Add a video to the pipeline queue for AV1 transcoding."""
    chat_id = normalize_channel_id(chat_id)
    conn = sqlite3.connect(QUEUE_DB_PATH)
    cur = conn.cursor()
    now = time.time()
    try:
        cur.execute("""
        INSERT OR IGNORE INTO pipeline_queue
            (chat_id, msg_id, file_name, file_size, duration, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
        """, (chat_id, msg_id, file_name, file_size, duration, now, now))
        conn.commit()
        if cur.rowcount > 0:
            logger.info(f"📥 Queued: {file_name} ({file_size / (1024*1024):.1f} MB) "
                       f"[chat={chat_id}, msg={msg_id}]")
        else:
            logger.debug(f"Already in queue: {file_name} [chat={chat_id}, msg={msg_id}]")
    finally:
        conn.close()


def get_pending_jobs(limit: int = 1) -> list:
    """Get pending jobs from the queue."""
    conn = sqlite3.connect(QUEUE_DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    SELECT id, chat_id, msg_id, file_name, file_size, duration, retry_count
    FROM pipeline_queue
    WHERE status = 'pending' AND retry_count < 3
    ORDER BY created_at ASC
    LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "chat_id": r[1], "msg_id": r[2],
            "file_name": r[3], "file_size": r[4],
            "duration": r[5], "retry_count": r[6]
        }
        for r in rows
    ]


def update_job_status(job_id: int, status: str, **kwargs):
    """Update a job's status and optional fields."""
    conn = sqlite3.connect(QUEUE_DB_PATH)
    cur = conn.cursor()
    sets = ["status = ?", "updated_at = ?"]
    vals = [status, time.time()]

    for key in ("colab_job_id", "new_msg_id", "error_msg", "retry_count"):
        if key in kwargs:
            sets.append(f"{key} = ?")
            vals.append(kwargs[key])

    vals.append(job_id)
    cur.execute(f"UPDATE pipeline_queue SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()
    conn.close()


def get_active_job_count() -> int:
    """Count currently running jobs."""
    conn = sqlite3.connect(QUEUE_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM pipeline_queue WHERE status = 'running'")
    count = cur.fetchone()[0]
    conn.close()
    return count


# ─── GAPT-CINEMA Database Updates ───────────────────────────────────────────
def update_cinema_db(chat_id: int, old_msg_id: int, new_msg_id: int,
                     file_name: str, file_size: int, duration: float,
                     width: int, height: int):
    """Update the main GAPT-CINEMA database with the new AV1 video entry."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Insert new entry for the AV1 version
    cur.execute("""
    INSERT INTO videos (chat_id, msg_id, file_name, file_size, mime_type,
                        duration, width, height, status, progress, qualities, updated_at)
    VALUES (?, ?, ?, ?, 'video/mp4', ?, ?, ?, 'ready', 100, '["source"]', ?)
    ON CONFLICT(chat_id, msg_id) DO UPDATE SET
        file_name=excluded.file_name,
        file_size=excluded.file_size,
        mime_type=excluded.mime_type,
        duration=excluded.duration,
        width=excluded.width,
        height=excluded.height,
        status=excluded.status,
        progress=excluded.progress,
        qualities=excluded.qualities,
        updated_at=excluded.updated_at
    """, (chat_id, new_msg_id, file_name, file_size, duration,
          width, height, time.time()))

    # Optionally mark old entry as replaced
    cur.execute("""
    UPDATE videos SET status = 'replaced'
    WHERE chat_id = ? AND msg_id = ? AND status != 'replaced'
    """, (chat_id, old_msg_id))

    conn.commit()
    conn.close()
    logger.info(f"✅ Cinema DB updated: new msg_id={new_msg_id}, old msg_id={old_msg_id} marked replaced")


# ─── Colab CLI Integration ──────────────────────────────────────────────────
COLAB_BIN = "/home/ubuntu/.local/bin/colab"

def check_colab_cli() -> bool:
    """Check if colab-cli is installed and functional."""
    try:
        result = subprocess.run([COLAB_BIN, "version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logger.info(f"Colab CLI version: {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        logger.warning(f"colab-cli not found at {COLAB_BIN}. Install with: pip install google-colab-cli")
    except Exception as e:
        logger.warning(f"colab-cli check failed: {e}")
    return False


async def run_colab_job(job: dict) -> dict:
    """
    Launch a Colab GPU job to transcode a video to AV1.
    Returns result dict with new_msg_id on success.
    """
    chat_id = job["chat_id"]
    msg_id = job["msg_id"]
    job_id = job["id"]

    logger.info(f"🚀 Launching Colab AV1 job for '{job['file_name']}' "
               f"[chat={chat_id}, msg={msg_id}]")

    # Prepare environment variables for the Colab script
    env_vars = {
        "CHAT_ID": str(chat_id),
        "MSG_ID": str(msg_id),
        "API_ID": str(API_ID),
        "API_HASH": API_HASH,
        "BOT_TOKEN": BOT_TOKEN,
    }

    # Attempt Colab execution (try GPU T4 first; if no compute units/quota, fallback to CPU)
    modes_to_try = ["gpu", "cpu"]
    last_error = ""

    for mode in modes_to_try:
        cmd_parts = [COLAB_BIN, "run"]
        if mode == "gpu":
            cmd_parts.extend(["--gpu", "T4"])
        cmd_parts.extend(["--timeout", "7200"])
        for k, v in env_vars.items():
            cmd_parts.extend(["--env", f"{k}={v}"])
        cmd_parts.append(str(COLAB_SCRIPT))

        logger.info(f"[COLAB] Running ({mode.upper()} mode): {' '.join(cmd_parts[:4])} ... {COLAB_SCRIPT.name}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(BASE_DIR),
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=7200  # 2 hour timeout
            )

            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")

            for line in stdout_text.split("\n"):
                if line.strip():
                    logger.info(f"[COLAB stdout] {line}")

            if proc.returncode != 0:
                logger.warning(f"[COLAB] {mode.upper()} run returned exit code {proc.returncode}")
                if "Service Unavailable" in stderr_text and mode == "gpu":
                    logger.warning("⚠️ Colab GPU T4 unavailable (quota/compute units). Falling back to Colab CPU mode...")
                    last_error = "GPU Service Unavailable"
                    continue
                last_error = f"Colab {mode} exit {proc.returncode}: {stderr_text[-300:]}"
                continue

            match = re.search(r"###PIPELINE_RESULT###(.+?)###END_RESULT###", stdout_text)
            if match:
                result = json.loads(match.group(1))
                logger.info(f"✅ Colab job succeeded ({mode.upper()}): new_msg_id={result.get('new_msg_id')}")
                return result
            else:
                logger.error(f"[COLAB] Could not parse pipeline result from {mode} output")
                last_error = "Result marker not found in output"

        except asyncio.TimeoutError:
            logger.error(f"[COLAB] {mode.upper()} job timed out")
            last_error = f"Colab {mode} timed out"
        except Exception as e:
            logger.error(f"[COLAB] {mode.upper()} exception: {e}")
            last_error = str(e)

    return {"status": "error", "error": last_error}


# ─── Fallback: Local CPU Transcoding ────────────────────────────────────────
async def run_local_transcode(job: dict, tg_client) -> dict:
    """
    Fallback: Run AV1 transcoding locally on OCI CPU when Colab is unavailable.
    Much slower but always available.
    """
    chat_id = job["chat_id"]
    msg_id = job["msg_id"]

    logger.info(f"⚙️ Local fallback transcode for '{job['file_name']}' "
               f"[chat={chat_id}, msg={msg_id}]")

    work_dir = BASE_DIR / "cache" / "pipeline_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    input_path = work_dir / f"input_{msg_id}.mp4"
    output_path = work_dir / f"av1_{msg_id}.mp4"

    try:
        # Download (supports both single file and multipart)
        msg = await tg_client.get_messages(chat_id, ids=msg_id)
        if not msg or not msg.media:
            return {"status": "error", "error": "Message not found or no media"}

        meta = None
        if msg.text:
            try:
                parsed = json.loads(msg.text)
                if isinstance(parsed, dict) and parsed.get("fileGroupId") and parsed.get("totalParts", 1) > 1:
                    meta = parsed
            except Exception:
                pass

        if meta:
            group_id = meta["fileGroupId"]
            total_parts = meta.get("totalParts", 1)
            parts_map = {meta.get("partIndex", 0): msg}
            search_range = range(max(1, msg_id - total_parts - 15), msg_id + total_parts + 16)
            candidates = [mid for mid in search_range if mid != msg_id]
            if candidates:
                cand_msgs = await tg_client.get_messages(chat_id, ids=candidates)
                for c in cand_msgs:
                    if c and c.media and c.text:
                        try:
                            c_meta = json.loads(c.text)
                            if isinstance(c_meta, dict) and c_meta.get("fileGroupId") == group_id:
                                parts_map[c_meta.get("partIndex", 0)] = c
                        except Exception:
                            pass
            logger.info(f"[LOCAL] Assembling {len(parts_map)} parts for multipart video...")
            with open(input_path, "wb") as outfile:
                for idx in sorted(parts_map.keys()):
                    p_msg = parts_map[idx]
                    temp_part = work_dir / f"temp_{msg_id}_part_{idx}.tmp"
                    await tg_client.download_media(p_msg, file=str(temp_part))
                    with open(temp_part, "rb") as infile:
                        while chunk := infile.read(16 * 1024 * 1024):
                            outfile.write(chunk)
                    temp_part.unlink(missing_ok=True)
        else:
            logger.info(f"[LOCAL] Downloading from Telegram...")
            await tg_client.download_media(msg, file=str(input_path))

        input_size = input_path.stat().st_size
        logger.info(f"[LOCAL] Downloaded & assembled: {input_size / (1024*1024):.1f} MB")

        # Probe
        probe_cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(input_path)
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        probe_data = json.loads(probe_result.stdout)
        duration = float(probe_data["format"].get("duration", 0))

        video_stream = next((s for s in probe_data.get("streams", [])
                            if s.get("codec_type") == "video"), None)
        width = int(video_stream.get("width", 0)) if video_stream else 0
        height = int(video_stream.get("height", 0)) if video_stream else 0

        # Calculate bitrate
        total_kbits = (SIZE_THRESHOLD_BYTES * 8) / 1000
        audio_kbits = 128 * duration
        target_kbps = max(500, min(12000, int((total_kbits - audio_kbits) / duration)))

        # Transcode (local CPU — slow but reliable)
        scale = ""
        if height > 1080:
            scale = "-vf scale=-2:1080"

        ffmpeg_cmd = (
            f"ffmpeg -y -i {input_path} "
            f"-c:v libsvtav1 -preset 8 -b:v {target_kbps}k "
            f"-maxrate {int(target_kbps * 1.2)}k -bufsize {int(target_kbps * 2)}k "
            f"-g 240 -pix_fmt yuv420p10le "
            f"{scale} "
            f"-c:a aac -b:a 128k -ac 2 "
            f"-movflags +faststart -f mp4 {output_path}"
        )

        logger.info(f"[LOCAL] Starting transcode (CPU, this will be slow)...")
        proc = await asyncio.create_subprocess_shell(
            ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_bytes = await proc.communicate()

        if proc.returncode != 0:
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")
            return {"status": "error", "error": f"FFmpeg failed: {stderr_text[-500:]}"}

        output_size = output_path.stat().st_size
        logger.info(f"[LOCAL] Transcode done: {output_size / (1024*1024):.1f} MB")

        # Upload back
        from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeFilename

        new_name = f"av1_{job['file_name'].rsplit('.', 1)[0]}.mp4"
        new_msg = await tg_client.send_file(
            chat_id,
            file=str(output_path),
            caption=f"🎬 AV1 Optimized | {output_size / (1024*1024):.0f} MB | Faststart ✅",
            reply_to=msg_id,
            attributes=[
                DocumentAttributeVideo(
                    duration=int(duration), w=width, h=height,
                    supports_streaming=True,
                ),
                DocumentAttributeFilename(file_name=new_name),
            ],
            force_document=False,
        )

        result = {
            "status": "success",
            "original_msg_id": msg_id,
            "new_msg_id": new_msg.id,
            "chat_id": chat_id,
            "file_name": new_name,
            "file_size": output_size,
            "duration": duration,
            "width": width,
            "height": height,
            "codec": "av1",
        }
        return result

    except Exception as e:
        logger.error(f"[LOCAL] Transcode failed: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        # Cleanup
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)


# ─── Cache Cleanup ───────────────────────────────────────────────────────────
def purge_pipeline_cache():
    """Remove temporary pipeline work files from SSD."""
    work_dir = BASE_DIR / "cache" / "pipeline_work"
    if work_dir.exists():
        for f in work_dir.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                    logger.debug(f"🗑️ Purged: {f.name}")
                except Exception as e:
                    logger.warning(f"Failed to purge {f.name}: {e}")


# ─── Telegram Event Listener ────────────────────────────────────────────────
async def setup_telegram_listener(tg_client):
    """
    Listen for new media messages in channels the bot has access to.
    Auto-queue videos that need AV1 optimization.
    """
    from telethon import events
    from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeFilename

    @tg_client.on(events.NewMessage(incoming=True))
    async def on_new_media(event):
        if not event.message or not event.message.media:
            return

        # Only process documents (files)
        doc = event.message.document
        if not doc:
            return

        # Check if it's a video file
        is_video = False
        file_name = "video.mp4"
        duration = 0
        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                is_video = True
                duration = attr.duration or 0
            if isinstance(attr, DocumentAttributeFilename):
                file_name = attr.file_name

        # Check if this is a TGDrive JSON-meta document
        meta = None
        if event.message.text:
            try:
                m_json = json.loads(event.message.text)
                if isinstance(m_json, dict) and m_json.get("v") == 2:
                    meta = m_json
            except Exception:
                pass

        chat_id = event.chat_id
        msg_id = event.message.id

        if meta and meta.get("fileGroupId") and meta.get("totalParts", 1) > 1:
            total_parts = meta.get("totalParts", 1)
            part_idx = meta.get("partIndex", 0)
            total_size = meta.get("size", doc.size or 0)
            real_name = meta.get("name", file_name)

            if part_idx == total_parts - 1 and total_size > SIZE_THRESHOLD_BYTES:
                logger.info(f"🎬 New large multipart video completed: '{real_name}' "
                           f"({total_size / (1024*1024):.0f} MB, {total_parts} parts) → queuing for AV1 pipeline")
                add_to_queue(chat_id, msg_id, real_name, total_size, duration)
                try:
                    await event.reply(
                        f"⏳ **วิดีโอรวมหลายตอนถูกเข้าคิวสำหรับแปลง AV1 อัตโนมัติ**\n\n"
                        f"📄 `{real_name}` ({total_size / (1024*1024):.0f} MB - {total_parts} ตอน)\n"
                        f"🔄 ระบบจะรวมไฟล์และแปลงให้เหลือ < 2 GB พร้อม Faststart\n"
                        f"📊 สถานะ: รอคิว...",
                        parse_mode="md",
                    )
                except Exception:
                    pass
            return

        if not is_video:
            # Check by filename extension
            ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
            if ext not in ("mp4", "mkv", "avi", "mov", "webm", "ts"):
                return
            is_video = True

        file_size = doc.size or 0

        # Queue for AV1 pipeline if video is large (> 1.95 GB)
        if file_size > SIZE_THRESHOLD_BYTES:
            logger.info(f"🎬 New large video detected: '{file_name}' "
                       f"({file_size / (1024*1024):.0f} MB) → queuing for AV1 pipeline")
            add_to_queue(chat_id, msg_id, file_name, file_size, duration)

            # Notify user
            try:
                await event.reply(
                    f"⏳ **วิดีโอถูกเข้าคิวสำหรับแปลง AV1 อัตโนมัติ**\n\n"
                    f"📄 `{file_name}` ({file_size / (1024*1024):.0f} MB)\n"
                    f"🔄 ระบบจะแปลงไฟล์ให้ < 2 GB พร้อม Faststart\n"
                    f"📊 สถานะ: รอคิว...",
                    parse_mode="md",
                )
            except Exception:
                pass
        else:
            logger.info(f"📁 New video: '{file_name}' ({file_size / (1024*1024):.0f} MB) "
                       f"— under limit, no AV1 needed")

    logger.info("📡 Telegram event listener active — monitoring for new uploads.")


# ─── Main Worker Loop ────────────────────────────────────────────────────────
async def worker_loop(tg_client):
    """Main loop: process queued jobs one at a time."""
    colab_available = check_colab_cli()
    if not colab_available:
        logger.warning("⚠️ Colab CLI not available — will use local CPU fallback (slower)")

    while True:
        try:
            # Check for active jobs
            active = get_active_job_count()
            if active >= MAX_CONCURRENT_JOBS:
                await asyncio.sleep(POLL_INTERVAL_SECS)
                continue

            # Get next pending job
            jobs = get_pending_jobs(limit=1)
            if not jobs:
                await asyncio.sleep(POLL_INTERVAL_SECS)
                continue

            job = jobs[0]
            logger.info(f"🔄 Processing job #{job['id']}: '{job['file_name']}'")
            update_job_status(job["id"], "running")

            # Try Colab first, fallback to local OCI transcode if Colab fails
            result = None
            if colab_available:
                result = await run_colab_job(job)
            if not result or result.get("status") != "success":
                err = result.get("error", "Colab unavailable") if result else "Colab not available"
                logger.warning(f"Colab execution failed ({err}). Falling back to local OCI transcode...")
                result = await run_local_transcode(job, tg_client)

            if result.get("status") == "success":
                # Update GAPT-CINEMA database
                update_cinema_db(
                    chat_id=result["chat_id"],
                    old_msg_id=result["original_msg_id"],
                    new_msg_id=result["new_msg_id"],
                    file_name=result["file_name"],
                    file_size=result["file_size"],
                    duration=result["duration"],
                    width=result["width"],
                    height=result["height"],
                )

                update_job_status(
                    job["id"], "completed",
                    new_msg_id=result["new_msg_id"]
                )

                # Send success notification via bot
                try:
                    await tg_client.send_message(
                        result["chat_id"],
                        f"✅ **AV1 Pipeline สำเร็จ!**\n\n"
                        f"📄 `{result['file_name']}`\n"
                        f"📦 ขนาด: {result['file_size'] / (1024*1024):.0f} MB\n"
                        f"🎥 ความละเอียด: {result['width']}x{result['height']}\n"
                        f"▶️ ดูออนไลน์: https://stream.capt-th.work/watch/{result['chat_id']}/{result['new_msg_id']}\n\n"
                        f"🎬 หนังถูกเพิ่มเข้า GAPT-CINEMA เรียบร้อย!",
                        parse_mode="md",
                        reply_to=result["new_msg_id"],
                    )
                except Exception as e:
                    logger.warning(f"Failed to send success notification: {e}")

                # Purge cache
                purge_pipeline_cache()
                logger.info(f"✅ Job #{job['id']} completed successfully.")

            else:
                error_msg = result.get("error", "Unknown error")
                retry_count = job["retry_count"] + 1

                if retry_count < 3:
                    update_job_status(
                        job["id"], "pending",
                        error_msg=error_msg,
                        retry_count=retry_count
                    )
                    logger.warning(f"⚠️ Job #{job['id']} failed (retry {retry_count}/3): {error_msg}")
                else:
                    update_job_status(
                        job["id"], "failed",
                        error_msg=error_msg,
                        retry_count=retry_count
                    )
                    logger.error(f"❌ Job #{job['id']} permanently failed: {error_msg}")

                    # Notify about failure
                    try:
                        await tg_client.send_message(
                            job["chat_id"],
                            f"❌ **AV1 Pipeline ล้มเหลว**\n\n"
                            f"📄 `{job['file_name']}`\n"
                            f"🔴 Error: {error_msg[:200]}",
                            parse_mode="md",
                            reply_to=job["msg_id"],
                        )
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"Worker loop error: {e}", exc_info=True)
            await asyncio.sleep(60)

        await asyncio.sleep(5)  # Brief pause between jobs


# ─── API Endpoint for Manual Queue ───────────────────────────────────────────
from aiohttp import web

async def handle_api_queue_add(request: web.Request):
    """POST /api/pipeline/queue — Manually add a video to the pipeline queue."""
    try:
        data = await request.json()
        chat_id = int(data["chat_id"])
        msg_id = int(data["msg_id"])
        file_name = data.get("file_name", "video.mp4")
        file_size = int(data.get("file_size", 0))
        duration = float(data.get("duration", 0))

        add_to_queue(chat_id, msg_id, file_name, file_size, duration)
        return web.json_response({"status": "queued", "chat_id": chat_id, "msg_id": msg_id})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=400)


async def handle_api_queue_status(request: web.Request):
    """GET /api/pipeline/status — Get pipeline queue status."""
    conn = sqlite3.connect(QUEUE_DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    SELECT id, chat_id, msg_id, file_name, file_size, status, retry_count, error_msg,
           created_at, updated_at
    FROM pipeline_queue
    ORDER BY created_at DESC
    LIMIT 50
    """)
    rows = cur.fetchall()
    conn.close()

    jobs = []
    for r in rows:
        jobs.append({
            "id": r[0], "chat_id": r[1], "msg_id": r[2],
            "file_name": r[3], "file_size": r[4],
            "status": r[5], "retry_count": r[6],
            "error": r[7],
            "created_at": r[8], "updated_at": r[9],
        })

    return web.json_response({
        "queue": jobs,
        "pending": sum(1 for j in jobs if j["status"] == "pending"),
        "running": sum(1 for j in jobs if j["status"] == "running"),
        "completed": sum(1 for j in jobs if j["status"] == "completed"),
        "failed": sum(1 for j in jobs if j["status"] == "failed"),
    })


# ─── Main Entry Point ───────────────────────────────────────────────────────
async def main():
    logger.info("═" * 60)
    logger.info("   GAPT-CINEMA Pipeline Worker Starting...")
    logger.info("═" * 60)

    if not API_ID or not API_HASH or not BOT_TOKEN:
        logger.error("Missing API_ID, API_HASH, or BOT_TOKEN. Check .env file.")
        sys.exit(1)

    # Initialize queue database
    init_queue_db()

    # Connect Telegram client
    from telethon import TelegramClient
    tg_client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await tg_client.start(bot_token=BOT_TOKEN)
    logger.info("✅ Telethon bot client connected.")

    # Setup event listener for new uploads
    await setup_telegram_listener(tg_client)

    # Start API server for manual queue management
    app = web.Application()
    app.router.add_post("/api/pipeline/queue", handle_api_queue_add)
    app.router.add_get("/api/pipeline/status", handle_api_queue_status)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8086)
    await site.start()
    logger.info("📡 Pipeline API listening on http://127.0.0.1:8086")

    # Start worker loop
    try:
        await worker_loop(tg_client)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await tg_client.disconnect()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
