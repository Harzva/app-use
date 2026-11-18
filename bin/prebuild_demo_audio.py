#!/usr/bin/env python3
"""Pre-synthesize natural 24kHz Kore PCM clips for zero-gap live Bot Studio demo playback."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DEFAULT_DATA_DIR = Path(os.environ.get("WECHAT_BOT_DATA_DIR") or "/Users/mac/Library/Application Support/WeChatBot")
PLAYBOOK_TEMPLATE = Path(__file__).resolve().parent.parent / "config_templates" / "botstudio_demo_playbook.json"
TARGET_PLAYBOOK = DEFAULT_DATA_DIR / "config" / "botstudio_demo_playbook.json"
CACHE_DIR = DEFAULT_DATA_DIR / "logs" / "demo_audio_cache"
GEMINI_API = "/Users/mac/.local/bin/gemini-api"


def _synth_one(item_id: str, text: str, voice: str, model: str) -> dict:
    wav_path = CACHE_DIR / f"{item_id}.wav"
    pcm_path = CACHE_DIR / f"{item_id}.pcm"
    meta_path = CACHE_DIR / f"{item_id}.json"

    if pcm_path.is_file() and meta_path.is_file():
        try:
            old = json.loads(meta_path.read_text(encoding="utf-8"))
            if old.get("text") == text and old.get("voice") == voice and pcm_path.stat().st_size > 8000:
                return {"id": item_id, "cached": True, "pcmBytes": pcm_path.stat().st_size, "wavPath": str(wav_path)}
        except Exception:
            pass

    env = dict(os.environ)
    env["HOME"] = "/Users/mac"
    env.setdefault("https_proxy", "http://127.0.0.1:7890")
    env.setdefault("http_proxy", "http://127.0.0.1:7890")

    import time
    models_to_try = [model]
    for alt in ("gemini-3.8-flash-lite-tts", "gemini-2.5-flash-preview-tts", "gemini-3.8-flash-tts"):
        if alt not in models_to_try:
            models_to_try.append(alt)

    used_model = model
    last_err = ""
    ok_tts = False
    for attempt in range(8):
        cur_model = models_to_try[attempt % len(models_to_try)]
        cmd = [GEMINI_API, "tts", text, "-m", cur_model, "-v", voice, "--out", str(wav_path), "-o", "json"]
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0 and wav_path.is_file() and wav_path.stat().st_size >= 2000:
            used_model = cur_model
            ok_tts = True
            break
        err_txt = proc.stderr or proc.stdout
        last_err = f"rc={proc.returncode} model={cur_model} err={err_txt}"
        if "429" in err_txt or "rate_limit" in err_txt or "too_many_requests" in err_txt:
            time.sleep(12 if attempt < 2 else 22)
        else:
            time.sleep(2)
    if not ok_tts:
        raise RuntimeError(f"gemini-api tts failed for {item_id}: {last_err}")
    model = used_model

    ff = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(wav_path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "24000",
            "-ac",
            "1",
            str(pcm_path),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if ff.returncode != 0 or not pcm_path.is_file() or pcm_path.stat().st_size < 4000:
        raise RuntimeError(f"ffmpeg pcm normalize failed for {item_id}: {ff.stderr}")

    pcm_bytes = pcm_path.stat().st_size
    duration_sec = round(pcm_bytes / (24000 * 2), 2)
    meta_path.write_text(
        json.dumps(
            {
                "id": item_id,
                "text": text,
                "voice": voice,
                "model": model,
                "wavPath": str(wav_path),
                "pcmPath": str(pcm_path),
                "pcmBytes": pcm_bytes,
                "durationSeconds": duration_sec,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "id": item_id,
        "cached": False,
        "pcmBytes": pcm_bytes,
        "durationSeconds": duration_sec,
        "wavPath": str(wav_path),
    }


def main() -> int:
    TARGET_PLAYBOOK.parent.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if PLAYBOOK_TEMPLATE.is_file():
        shutil.copy2(PLAYBOOK_TEMPLATE, TARGET_PLAYBOOK)

    playbook = json.loads(TARGET_PLAYBOOK.read_text(encoding="utf-8"))
    voice = str(playbook.get("voice") or "Kore")
    model = str(playbook.get("model") or "gemini-3.8-flash-tts")
    items = []
    for ack in playbook.get("acknowledgements") or []:
        items.append((ack["id"], ack["text"]))
    rb = playbook.get("resumeBridge")
    if isinstance(rb, dict) and rb.get("id") and rb.get("text"):
        items.append((rb["id"], rb["text"]))
    for beat in playbook.get("beats") or []:
        items.append((beat["id"], beat["text"]))

    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(_synth_one, item_id, text, voice, model): item_id for item_id, text in items}
        for fut in as_completed(futs):
            results.append(fut.result())

    results.sort(key=lambda r: r["id"])
    print(json.dumps({"ok": True, "count": len(results), "cacheDir": str(CACHE_DIR), "items": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
