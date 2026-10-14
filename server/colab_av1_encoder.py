#!/usr/bin/env python3
"""
GAPT-CINEMA — Google Colab AV1 Encoder Script
Runs on Colab GPU (T4) via `colab exec` from OCI pipeline worker.

Flow:
  1. Receives Telegram chat_id + msg_id + credentials via environment
  2. Downloads the original video from Telegram via Telethon
  3. Probes video metadata (duration, resolution, codecs)
  4. Calculates target bitrate to fit under 1.95 GB
  5. Transcodes to AV1 (libsvtav1) + AAC with Faststart
  6. Uploads the result back to Telegram as a new message (reply to original)
  7. Prints the new message ID for the OCI worker to capture

Usage (called by pipeline_worker.py via colab-cli):
  colab exec -f colab_av1_encoder.py --gpu T4

Environment Variables (injected by pipeline_worker.py):
  CHAT_ID, MSG_ID, API_ID, API_HASH, BOT_TOKEN
"""

import os
import sys
import json
import time
import asyncio
import subprocess
import shutil
from pathlib import Path

# ─── Install dependencies in Colab ──────────────────────────────────────────
def install_deps():
    """Install required packages in Colab environment."""
    subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                    "telethon", "cryptg"], check=True)
    # Ensure ffmpeg with SVT-AV1 support is available
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
    if result.returncode != 0:
        subprocess.run(["apt-get", "install", "-y", "-qq", "ffmpeg"], check=True)
    print("[OK] Dependencies ready.")

install_deps()

from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeFilename

# ─── Configuration ───────────────────────────────────────────────────────────
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
raw_chat_id = int(os.environ["CHAT_ID"])
CHAT_ID = -int(f"100{raw_chat_id}") if raw_chat_id > 0 else raw_chat_id
MSG_ID = int(os.environ["MSG_ID"])

WORK_DIR = Path("/tmp/gapt_pipeline")
WORK_DIR.mkdir(parents=True, exist_ok=True)

MAX_OUTPUT_BYTES = 1_950 * 1024 * 1024  # 1.95 GB (safe margin under 2.0 GB Telegram limit)
MAX_AUDIO_BITRATE_KBPS = 128

# ─── Helpers ─────────────────────────────────────────────────────────────────
def probe_video(path: Path) -> dict:
    """Probe video file with ffprobe, return metadata dict."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    video_stream = None
    audio_stream = None
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not video_stream:
            video_stream = s
        elif s.get("codec_type") == "audio" and not audio_stream:
            audio_stream = s

    duration = float(data["format"].get("duration", 0))
    width = int(video_stream.get("width", 0)) if video_stream else 0
    height = int(video_stream.get("height", 0)) if video_stream else 0
    codec = video_stream.get("codec_name", "unknown") if video_stream else "unknown"
    file_size = int(data["format"].get("size", 0))

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "codec": codec,
        "file_size": file_size,
        "has_audio": audio_stream is not None,
    }


def calculate_target_bitrate(duration_secs: float) -> int:
    """Calculate target video bitrate (kbps) to fit under MAX_OUTPUT_BYTES."""
    if duration_secs <= 0:
        return 4000  # fallback 4 Mbps

    total_kbits = (MAX_OUTPUT_BYTES * 8) / 1000
    audio_kbits = MAX_AUDIO_BITRATE_KBPS * duration_secs
    video_kbits = total_kbits - audio_kbits
    target_kbps = int(video_kbits / duration_secs)

    # Clamp: minimum 500 kbps, maximum 12000 kbps
    return max(500, min(target_kbps, 12000))


def transcode_av1(input_path: Path, output_path: Path, target_kbps: int, meta: dict):
    """Transcode video to AV1 (libsvtav1) + AAC with Faststart using 2-pass."""
    height = meta["height"]
    width = meta["width"]
    scale_filter = ""
    if height > 1080:
        scale_filter = "-vf scale=-2:1080"
    elif height > 0 and height % 2 != 0:
        scale_filter = f"-vf scale=-2:{height - 1}"

    # Check if GPU is active
    has_gpu = False
    try:
        gpu_check = subprocess.run(["nvidia-smi"], capture_output=True, timeout=5)
        has_gpu = gpu_check.returncode == 0
    except Exception:
        pass

    preset = "6" if has_gpu else "10"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-c:v", "libsvtav1",
        "-preset", preset,
        "-b:v", f"{target_kbps}k",
        "-maxrate", f"{int(target_kbps * 1.2)}k",
        "-bufsize", f"{int(target_kbps * 2)}k",
        "-g", "240",
        "-pix_fmt", "yuv420p10le",
    ]

    if scale_filter:
        cmd.extend(scale_filter.split())

    if meta["has_audio"]:
        cmd.extend(["-c:a", "aac", "-b:a", f"{MAX_AUDIO_BITRATE_KBPS}k", "-ac", "2"])
    else:
        cmd.extend(["-an"])

    cmd.extend([
        "-movflags", "+faststart",
        "-f", "mp4",
        str(output_path)
    ])

    print(f"[TRANSCODE] Target bitrate: {target_kbps} kbps")
    print(f"[TRANSCODE] Command: {' '.join(cmd)}")

    start_time = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)

    elapsed = time.time() - start_time
    print(f"[TRANSCODE] Finished in {elapsed:.1f}s (exit code: {proc.returncode})")

    if proc.returncode != 0:
        print(f"[ERROR] FFmpeg stderr:\n{proc.stderr[-2000:]}")
        raise RuntimeError(f"FFmpeg transcode failed with exit code {proc.returncode}")

    output_size = output_path.stat().st_size
    print(f"[TRANSCODE] Output size: {output_size / (1024*1024):.1f} MB")

    if output_size > MAX_OUTPUT_BYTES:
        print(f"[WARNING] Output exceeds {MAX_OUTPUT_BYTES/(1024*1024):.0f} MB limit! "
              f"Re-encoding with lower bitrate...")
        retry_kbps = int(target_kbps * 0.85)
        output_path.unlink(missing_ok=True)
        cmd_retry = [c.replace(f"{target_kbps}k", f"{retry_kbps}k")
                     .replace(f"{int(target_kbps * 1.2)}k", f"{int(retry_kbps * 1.2)}k")
                     .replace(f"{int(target_kbps * 2)}k", f"{int(retry_kbps * 2)}k")
                     for c in cmd]
        proc2 = subprocess.run(cmd_retry, capture_output=True, text=True)
        if proc2.returncode != 0:
            raise RuntimeError(f"Retry transcode failed: {proc2.stderr[-1000:]}")
        output_size = output_path.stat().st_size
        print(f"[TRANSCODE] Retry output size: {output_size / (1024*1024):.1f} MB")

    return output_size


async def download_media_or_multipart(client, chat_id: int, msg_id: int, work_dir: Path):
    """
    Download a single file or assemble a multi-part file from Telegram.
    TGDrive splits large files (>1.95GB) into parts with a JSON caption containing
    fileGroupId, partIndex, and totalParts.
    """
    msg = await client.get_messages(chat_id, ids=msg_id)
    if not msg or not msg.media:
        raise ValueError(f"Message {msg_id} not found or has no media in chat {chat_id}")

    meta = None
    if msg.text:
        try:
            parsed = json.loads(msg.text)
            if isinstance(parsed, dict) and parsed.get("fileGroupId") and parsed.get("totalParts", 1) > 1:
                meta = parsed
        except Exception:
            pass

    if not meta:
        # Single file
        orig_name = "video.mp4"
        if msg.document:
            for attr in msg.document.attributes:
                if isinstance(attr, DocumentAttributeFilename):
                    orig_name = attr.file_name
                    break
        input_path = work_dir / f"input_{orig_name}"
        print(f"[DOWNLOAD] Downloading single message {msg_id} ('{orig_name}')...")
        dl_start = time.time()
        await client.download_media(msg, file=str(input_path))
        dl_elapsed = time.time() - dl_start
        print(f"[DOWNLOAD] Done in {dl_elapsed:.1f}s")
        return input_path, orig_name, msg

    # Multi-part grouped file
    group_id = meta["fileGroupId"]
    total_parts = meta.get("totalParts", 1)
    orig_name = meta.get("name", "video.mp4")
    input_path = work_dir / f"input_{orig_name}"
    print(f"[DOWNLOAD] Detected {total_parts}-part file: '{orig_name}' (GroupID: {group_id})")

    parts_map = {meta.get("partIndex", 0): msg}
    search_range = range(max(1, msg_id - total_parts - 15), msg_id + total_parts + 16)
    candidates = [mid for mid in search_range if mid != msg_id]
    if candidates:
        cand_msgs = await client.get_messages(chat_id, ids=candidates)
        for c in cand_msgs:
            if c and c.media and c.text:
                try:
                    c_meta = json.loads(c.text)
                    if isinstance(c_meta, dict) and c_meta.get("fileGroupId") == group_id:
                        p_idx = c_meta.get("partIndex", 0)
                        parts_map[p_idx] = c
                except Exception:
                    pass

    if len(parts_map) != total_parts:
        print(f"[WARNING] Found {len(parts_map)} of {total_parts} parts in search range. Expanding search...")
        wide_range = range(max(1, msg_id - 50), msg_id + 51)
        wide_cands = [mid for mid in wide_range if mid not in [m.id for m in parts_map.values()]]
        if wide_cands:
            cand_msgs = await client.get_messages(chat_id, ids=wide_cands)
            for c in cand_msgs:
                if c and c.media and c.text:
                    try:
                        c_meta = json.loads(c.text)
                        if isinstance(c_meta, dict) and c_meta.get("fileGroupId") == group_id:
                            parts_map[c_meta.get("partIndex", 0)] = c
                    except Exception:
                        pass

    if len(parts_map) != total_parts:
        missing = [i for i in range(total_parts) if i not in parts_map]
        raise RuntimeError(f"Cannot assemble multipart: missing part indexes {missing} (found {len(parts_map)} of {total_parts})")

    print(f"[DOWNLOAD] Assembling {total_parts} parts sequentially into {input_path.name}...")
    dl_start = time.time()
    with open(input_path, "wb") as outfile:
        for idx in sorted(parts_map.keys()):
            p_msg = parts_map[idx]
            temp_part = work_dir / f"temp_part_{idx}.tmp"
            print(f"[DOWNLOAD] Downloading part {idx + 1}/{total_parts} (message {p_msg.id})...")
            await client.download_media(p_msg, file=str(temp_part))
            with open(temp_part, "rb") as infile:
                while chunk := infile.read(16 * 1024 * 1024):
                    outfile.write(chunk)
            temp_part.unlink(missing_ok=True)
            print(f"[DOWNLOAD] Appended part {idx + 1}/{total_parts} ✅")

    dl_elapsed = time.time() - dl_start
    input_size = input_path.stat().st_size
    print(f"[DOWNLOAD] Full assembled file: {input_size / (1024*1024):.1f} MB in {dl_elapsed:.1f}s")
    return input_path, orig_name, msg


# ─── Main Pipeline ───────────────────────────────────────────────────────────
async def main():
    print(f"[PIPELINE] Starting AV1 encode for chat={CHAT_ID} msg={MSG_ID}")

    session_path = str(WORK_DIR / "bot_colab")
    client = TelegramClient(session_path, API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    print("[OK] Telethon bot client connected.")

    # Step 1 & 2: Fetch and download (with multipart support)
    input_path, orig_name, orig_msg = await download_media_or_multipart(client, CHAT_ID, MSG_ID, WORK_DIR)
    input_size = input_path.stat().st_size
    output_path = WORK_DIR / f"av1_{orig_name.rsplit('.', 1)[0]}.mp4"

    # Step 3: Probe metadata
    meta = probe_video(input_path)
    print(f"[PROBE] Duration: {meta['duration']:.1f}s, "
          f"Resolution: {meta['width']}x{meta['height']}, "
          f"Codec: {meta['codec']}")

    # Step 4: Check if already small enough (skip transcode if < 1.95 GB and already AV1)
    if input_size <= MAX_OUTPUT_BYTES and meta["codec"] == "av1":
        print("[SKIP] File is already AV1 and under size limit. Applying Faststart only...")
        faststart_cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-c", "copy", "-movflags", "+faststart",
            "-f", "mp4", str(output_path)
        ]
        subprocess.run(faststart_cmd, check=True, capture_output=True)
    else:
        # Step 5: Calculate bitrate and transcode
        target_kbps = calculate_target_bitrate(meta["duration"])
        transcode_av1(input_path, output_path, target_kbps, meta)

    # Clean up input file to free Colab disk
    input_path.unlink(missing_ok=True)

    # Step 6: Probe output for upload attributes
    out_meta = probe_video(output_path)
    output_size = output_path.stat().st_size

    # Step 7: Upload back to Telegram (with TGDrive metadata)
    print(f"[UPLOAD] Uploading AV1 file ({output_size / (1024*1024):.1f} MB) to Telegram...")
    ul_start = time.time()

    new_name = f"av1_{orig_name.rsplit('.', 1)[0]}.mp4"
    caption_meta = {
        "v": 2,
        "name": new_name,
        "size": output_size,
        "mime": "video/mp4",
        "uploadedAt": int(time.time() * 1000),
        "totalParts": 1,
        "codec": "av1",
    }
    caption_text = json.dumps(caption_meta)

    new_msg = await client.send_file(
        CHAT_ID,
        file=str(output_path),
        caption=caption_text,
        reply_to=MSG_ID,
        attributes=[
            DocumentAttributeVideo(
                duration=int(out_meta["duration"]),
                w=out_meta["width"],
                h=out_meta["height"],
                supports_streaming=True,
            ),
            DocumentAttributeFilename(file_name=new_name),
        ],
        force_document=False,
    )

    ul_elapsed = time.time() - ul_start
    print(f"[UPLOAD] Done in {ul_elapsed:.1f}s")

    # Step 8: Output result for OCI worker to parse
    result = {
        "status": "success",
        "original_msg_id": MSG_ID,
        "new_msg_id": new_msg.id,
        "chat_id": CHAT_ID,
        "file_name": new_name,
        "file_size": output_size,
        "duration": out_meta["duration"],
        "width": out_meta["width"],
        "height": out_meta["height"],
        "codec": "av1",
    }
    print(f"\n###PIPELINE_RESULT###{json.dumps(result)}###END_RESULT###")

    # Cleanup
    output_path.unlink(missing_ok=True)
    await client.disconnect()
    print("[DONE] Colab AV1 encoder finished successfully.")


if __name__ == "__main__":
    asyncio.run(main())
