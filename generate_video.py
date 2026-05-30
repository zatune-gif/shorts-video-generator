#!/usr/bin/env python3
"""
YouTube Shorts 自動生成スクリプト
Usage: python generate_video.py [config.json]
"""

import json
import sys
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    AudioFileClip, CompositeAudioClip, CompositeVideoClip,
    VideoClip, concatenate_audioclips,
)

# ── YouTube Shorts 設定 ──────────────────────────────────
WIDTH, HEIGHT = 1080, 1920
FPS = 30
FONT_PATH     = "C:/Windows/Fonts/meiryo.ttc"
VOICEVOX_URL  = "http://localhost:50021"

# デザイン定数
TITLE_FONT_SIZE = 72
DESC_FONT_SIZE  = 46
OVERLAY_H       = 340
ZOOM_AMOUNT     = 0.08
TRANSITION_SEC  = 0.5
FADE_SEC        = 0.8
BGM_VOLUME        = 0.18
BGM_FADEOUT_SEC   = 2.0
NARRATION_VOLUME  = 2.0


# ── TTS ─────────────────────────────────────────────────

def _voicevox_available() -> bool:
    try:
        return requests.get(f"{VOICEVOX_URL}/version", timeout=2).ok
    except Exception:
        return False


def _voicevox_speak(text: str, speaker_id: int, path: Path,
                    speed: float, pitch: float) -> None:
    r = requests.post(
        f"{VOICEVOX_URL}/audio_query",
        params={"text": text, "speaker": speaker_id},
    )
    r.raise_for_status()
    query = r.json()
    query["speedScale"]        = speed
    query["pitchScale"]        = pitch
    query["outputSamplingRate"] = 44100

    r = requests.post(
        f"{VOICEVOX_URL}/synthesis",
        headers={"Content-Type": "application/json"},
        params={"speaker": speaker_id},
        data=json.dumps(query),
    )
    r.raise_for_status()
    path.write_bytes(r.content)


def _windows_speak(text: str, path: Path) -> None:
    import pyttsx3
    engine = pyttsx3.init()
    for v in engine.getProperty("voices"):
        if "ja" in v.id.lower() or "japanese" in v.name.lower():
            engine.setProperty("voice", v.id)
            break
    engine.setProperty("rate", 135)
    engine.save_to_file(text, str(path))
    engine.runAndWait()


def make_narration(tts_cfg: dict, out_path: Path) -> None:
    text      = tts_cfg.get("text", "")
    engine    = tts_cfg.get("engine", "voicevox").lower()
    speaker   = int(tts_cfg.get("speaker_id", 3))
    speed     = float(tts_cfg.get("speed", 1.0))
    pitch     = float(tts_cfg.get("pitch", 0.0))

    if engine == "voicevox":
        if _voicevox_available():
            print(f"  VOICEVOX: speaker={speaker}  speed={speed}  pitch={pitch}")
            _voicevox_speak(text, speaker, out_path, speed, pitch)
        else:
            print("  [!] VOICEVOX が起動していません → Windows TTS で代替します")
            _windows_speak(text, out_path)
    else:
        print("  Windows TTS (Haruka)")
        _windows_speak(text, out_path)


# ── 画像処理 ─────────────────────────────────────────────

def center_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.convert("RGB")
    sw, sh = img.size
    if sw / sh > w / h:
        nw = int(sh * w / h)
        img = img.crop(((sw - nw) // 2, 0, (sw + nw) // 2, sh))
    else:
        nh = int(sw * h / w)
        img = img.crop((0, (sh - nh) // 2, sw, (sh + nh) // 2))
    return img.resize((w, h), Image.LANCZOS)


def draw_text_overlay(img: Image.Image, title: str, description: str) -> Image.Image:
    canvas = img.convert("RGBA")
    bar    = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d      = ImageDraw.Draw(bar)
    d.rectangle([(0, HEIGHT - OVERLAY_H), (WIDTH, HEIGHT)], fill=(0, 0, 0, 170))
    canvas = Image.alpha_composite(canvas, bar).convert("RGB")
    draw   = ImageDraw.Draw(canvas)

    try:
        t_font = ImageFont.truetype(FONT_PATH, TITLE_FONT_SIZE)
        d_font = ImageFont.truetype(FONT_PATH, DESC_FONT_SIZE)
    except OSError:
        t_font = d_font = ImageFont.load_default()

    ty = HEIGHT - OVERLAY_H + 40
    dy = ty + TITLE_FONT_SIZE + 18
    for font, text, y in [(t_font, title, ty), (d_font, description, dy)]:
        draw.text((52, y + 2), text, font=font, fill=(0, 0, 0))
        draw.text((50, y),     text, font=font, fill=(255, 255, 255))

    return canvas


def make_ken_burns(img: Image.Image, duration: float, zoom_in: bool) -> VideoClip:
    arr  = np.array(img.convert("RGB"))
    H, W = arr.shape[:2]

    def frame(t: float):
        p     = t / duration
        zoom  = (1.0 + ZOOM_AMOUNT * p) if zoom_in else (1.0 + ZOOM_AMOUNT * (1.0 - p))
        cw    = int(W / zoom)
        ch    = int(H / zoom)
        x0    = (W - cw) // 2
        y0    = (H - ch) // 2
        patch = arr[y0:y0 + ch, x0:x0 + cw]
        return np.array(Image.fromarray(patch).resize((W, H), Image.BILINEAR))

    return VideoClip(frame, duration=duration).set_fps(FPS)


def loop_bgm(bgm_path: str, target_sec: float, volume: float = BGM_VOLUME) -> AudioFileClip:
    bgm = AudioFileClip(bgm_path)
    if bgm.duration < target_sec:
        loops = int(target_sec / bgm.duration) + 2
        bgm   = concatenate_audioclips([bgm] * loops)
    return (bgm
            .subclip(0, target_sec)
            .volumex(volume)
            .audio_fadeout(BGM_FADEOUT_SEC))


# ── メイン ───────────────────────────────────────────────

def generate(config_path: str = "config.json") -> None:
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)

    title       = cfg.get("title", "")
    description = cfg.get("description", "")
    tts_cfg     = cfg.get("tts")
    narr_path   = Path(cfg.get("narration", "input/narration.wav"))
    bgm_path    = cfg.get("bgm", "")
    img_paths   = cfg["images"]
    out_path    = cfg.get("output", "output/video.mp4")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    # ── ナレーション準備 ──────────────────────────────────
    if tts_cfg and tts_cfg.get("text"):
        print("Generating narration ...")
        make_narration(tts_cfg, narr_path)
    elif not narr_path.exists():
        print(f"Error: narration file not found: {narr_path}")
        sys.exit(1)

    # ── 尺を音声から決定 ─────────────────────────────────
    print("Loading narration ...")
    narration   = AudioFileClip(str(narr_path))
    total_sec   = min(narration.duration, 59.0)
    narration   = narration.subclip(0, total_sec)
    n           = len(img_paths)
    dur_per_img = (total_sec + (n - 1) * TRANSITION_SEC) / n

    print(f"Duration: {total_sec:.1f}s | {n} images x {dur_per_img:.1f}s | FPS:{FPS}")

    # ── 画像クリップ生成 ─────────────────────────────────
    clips = []
    for i, path in enumerate(img_paths):
        print(f"  [{i+1}/{n}] {path}")
        img = Image.open(path)
        img = center_crop(img, WIDTH, HEIGHT)
        img = draw_text_overlay(img, title, description)

        clip  = make_ken_burns(img, dur_per_img, zoom_in=(i % 2 == 0))
        start = i * (dur_per_img - TRANSITION_SEC)
        clip  = clip.set_start(start)
        if i == 0:
            clip = clip.fadein(FADE_SEC)
        if i > 0:
            clip = clip.crossfadein(TRANSITION_SEC)
        if i == n - 1:
            clip = clip.fadeout(FADE_SEC)
        clips.append(clip)

    video = CompositeVideoClip(clips, size=(WIDTH, HEIGHT)).set_duration(total_sec)

    # ── 音声合成 ─────────────────────────────────────────
    narration = narration.volumex(cfg.get("narration_volume", NARRATION_VOLUME))

    if bgm_path and Path(bgm_path).exists():
        print("Mixing BGM ...")
        bgm   = loop_bgm(bgm_path, total_sec, cfg.get("bgm_volume", BGM_VOLUME))
        audio = CompositeAudioClip([narration, bgm])
    else:
        audio = narration

    video = video.set_audio(audio)

    # ── エクスポート ─────────────────────────────────────
    print(f"Rendering -> {out_path}")
    video.write_videofile(
        out_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        bitrate="8000k",
        audio_bitrate="192k",
        preset="medium",
        threads=4,
        logger="bar",
    )
    print("Done!")


if __name__ == "__main__":
    cfg = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    generate(cfg)
