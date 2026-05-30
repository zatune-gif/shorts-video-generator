#!/usr/bin/env python3
"""
YouTube Shorts 動画生成スクリプト
app.py から呼び出されるほか、単体でも実行できます。
Usage: python generate_video.py [config.json]
"""

import json
import re
import sys
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    AudioFileClip, CompositeAudioClip, CompositeVideoClip,
    VideoClip, concatenate_audioclips,
)

# ── 動画仕様 ──────────────────────────────────────────────
WIDTH,  HEIGHT = 1080, 1920
FPS            = 30
FONT_PATH      = "C:/Windows/Fonts/meiryo.ttc"
VOICEVOX_URL   = "http://localhost:50021"

# ── テキストオーバーレイ ──────────────────────────────────
TITLE_FONT_SIZE = 72
DESC_FONT_SIZE  = 46
OVERLAY_HEIGHT  = 340

# ── アニメーション ────────────────────────────────────────
ZOOM_AMOUNT    = 0.08
TRANSITION_SEC = 0.5
FADE_SEC       = 0.8

# ── 音量デフォルト値（config.json で上書き可） ────────────
DEFAULT_BGM_VOLUME  = 0.18
DEFAULT_NARR_VOLUME = 2.0
BGM_FADEOUT_SEC     = 2.0


# ── 音声合成（VOICEVOX） ──────────────────────────────────

def _voicevox_available() -> bool:
    try:
        return requests.get(f"{VOICEVOX_URL}/version", timeout=2).ok
    except Exception:
        return False


def _synthesize_voicevox(text: str, speaker_id: int, speed: float,
                          pitch: float, out_path: Path) -> None:
    r = requests.post(f"{VOICEVOX_URL}/audio_query",
                      params={"text": text, "speaker": speaker_id})
    r.raise_for_status()
    query = r.json()
    query["speedScale"]         = speed
    query["pitchScale"]         = pitch
    query["outputSamplingRate"] = 44100

    r = requests.post(f"{VOICEVOX_URL}/synthesis",
                      headers={"Content-Type": "application/json"},
                      params={"speaker": speaker_id},
                      data=json.dumps(query))
    r.raise_for_status()
    out_path.write_bytes(r.content)


def _synthesize_windows_tts(text: str, out_path: Path) -> None:
    import pyttsx3
    engine = pyttsx3.init()
    for voice in engine.getProperty("voices"):
        if "ja" in voice.id.lower() or "japanese" in voice.name.lower():
            engine.setProperty("voice", voice.id)
            break
    engine.setProperty("rate", 135)
    engine.save_to_file(text, str(out_path))
    engine.runAndWait()


def _strip_ruby(text: str) -> str:
    """{漢字|よみ} 記法を読み仮名のみに変換して返す"""
    return re.sub(r'\{([^|{}]+)\|([^|{}]+)\}', r'\2', text)


def make_narration(tts_cfg: dict, out_path: Path) -> None:
    text    = _strip_ruby(tts_cfg.get("text", ""))
    engine  = tts_cfg.get("engine", "voicevox").lower()
    speaker = int(tts_cfg.get("speaker_id", 3))
    speed   = float(tts_cfg.get("speed", 1.0))
    pitch   = float(tts_cfg.get("pitch", 0.0))

    if engine == "voicevox" and _voicevox_available():
        print(f"  VOICEVOX: speaker={speaker}  speed={speed}  pitch={pitch}")
        _synthesize_voicevox(text, speaker, speed, pitch, out_path)
    else:
        if engine == "voicevox":
            print("  [!] VOICEVOX が起動していません → Windows TTS で代替します")
        else:
            print("  Windows TTS")
        _synthesize_windows_tts(text, out_path)


# ── 画像処理 ──────────────────────────────────────────────

def center_crop(img: Image.Image, w: int, h: int,
                h_offset: int = 0, v_offset: int = 0) -> Image.Image:
    """
    縦横比を保ちながらクロップしてリサイズ。
    h_offset: -100〜+100（負=左寄り、正=右寄り）横長画像に有効
    v_offset: -100〜+100（負=上寄り、正=下寄り）縦長画像に有効
    """
    img = img.convert("RGB")
    sw, sh = img.size
    if sw / sh > w / h:
        nw     = int(sh * w / h)
        margin = (sw - nw) // 2
        shift  = int(margin * h_offset / 100)
        x0     = max(0, min(margin + shift, sw - nw))
        img    = img.crop((x0, 0, x0 + nw, sh))
    else:
        nh     = int(sw * h / w)
        margin = (sh - nh) // 2
        shift  = int(margin * v_offset / 100)
        y0     = max(0, min(margin + shift, sh - nh))
        img    = img.crop((0, y0, sw, y0 + nh))
    return img.resize((w, h), Image.LANCZOS)


def draw_text_overlay(img: Image.Image, title: str, description: str) -> Image.Image:
    """動画下部に半透明バー＋テキストを描画"""
    canvas = img.convert("RGBA")
    bar    = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d      = ImageDraw.Draw(bar)
    d.rectangle([(0, HEIGHT - OVERLAY_HEIGHT), (WIDTH, HEIGHT)], fill=(0, 0, 0, 170))
    canvas = Image.alpha_composite(canvas, bar).convert("RGB")
    draw   = ImageDraw.Draw(canvas)

    try:
        title_font = ImageFont.truetype(FONT_PATH, TITLE_FONT_SIZE)
        desc_font  = ImageFont.truetype(FONT_PATH, DESC_FONT_SIZE)
    except OSError:
        title_font = desc_font = ImageFont.load_default()

    ty = HEIGHT - OVERLAY_HEIGHT + 40
    dy = ty + TITLE_FONT_SIZE + 18
    for font, text, y in [(title_font, title, ty), (desc_font, description, dy)]:
        draw.text((52, y + 2), text, font=font, fill=(0, 0, 0))
        draw.text((50, y),     text, font=font, fill=(255, 255, 255))

    return canvas


def make_ken_burns(img: Image.Image, duration: float, zoom_in: bool) -> VideoClip:
    """ズームイン／アウトのケンバーンズエフェクトを適用したクリップを生成"""
    arr  = np.array(img.convert("RGB"))
    h, w = arr.shape[:2]

    def frame(t: float):
        progress = t / duration
        zoom     = 1.0 + ZOOM_AMOUNT * (progress if zoom_in else 1.0 - progress)
        cw = int(w / zoom)
        ch = int(h / zoom)
        x0 = (w - cw) // 2
        y0 = (h - ch) // 2
        patch = arr[y0:y0 + ch, x0:x0 + cw]
        return np.array(Image.fromarray(patch).resize((w, h), Image.BILINEAR))

    return VideoClip(frame, duration=duration).set_fps(FPS)


# ── 音声処理 ──────────────────────────────────────────────

def loop_bgm(bgm_path: str, target_sec: float, volume: float) -> AudioFileClip:
    """BGM を必要な長さにループし、フェードアウトを付けて返す"""
    bgm = AudioFileClip(bgm_path)
    if bgm.duration < target_sec:
        loops = int(target_sec / bgm.duration) + 2
        bgm   = concatenate_audioclips([bgm] * loops)
    return bgm.subclip(0, target_sec).volumex(volume).audio_fadeout(BGM_FADEOUT_SEC)


# ── 動画生成メイン ────────────────────────────────────────

def generate(config_path: str = "config.json") -> None:
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)

    title        = cfg.get("title", "")
    description  = cfg.get("description", "")
    tts_cfg      = cfg.get("tts")
    narr_path    = Path(cfg.get("narration", "input/narration.wav"))
    bgm_path     = cfg.get("bgm", "")
    img_paths    = cfg["images"]
    out_path     = cfg.get("output", "output/video.mp4")
    bgm_volume   = cfg.get("bgm_volume",      DEFAULT_BGM_VOLUME)
    narr_volume  = cfg.get("narration_volume", DEFAULT_NARR_VOLUME)
    manual_dur   = cfg.get("duration")          # None = 自動、数値 = 手動指定（秒）
    crop_h       = cfg.get("crop_h_offset", 0)  # -100〜+100
    crop_v       = cfg.get("crop_v_offset", 0)  # -100〜+100

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    # ナレーション生成
    if tts_cfg and tts_cfg.get("text"):
        print("Generating narration ...")
        make_narration(tts_cfg, narr_path)
    elif not narr_path.exists():
        print(f"Error: narration file not found: {narr_path}")
        sys.exit(1)

    # 動画の総時間を決定（最大59秒）
    print("Loading narration ...")
    narration = AudioFileClip(str(narr_path))
    if manual_dur:
        total_sec = min(float(manual_dur), 59.0)
        # ナレーションが指定秒数より短い場合はそのまま使い、残りは無音になる
        narration = narration.subclip(0, min(total_sec, narration.duration))
        print(f"  Duration: manual={manual_dur}s → {total_sec:.1f}s (narration: {narration.duration:.1f}s)")
    else:
        total_sec = min(narration.duration, 59.0)
        narration = narration.subclip(0, total_sec)
    n           = len(img_paths)
    dur_per_img = (total_sec + (n - 1) * TRANSITION_SEC) / n

    print(f"Duration: {total_sec:.1f}s | {n} images x {dur_per_img:.1f}s | FPS: {FPS}")

    # 各画像からケンバーンズクリップを生成
    clips = []
    for i, path in enumerate(img_paths):
        print(f"  [{i + 1}/{n}] {path}")
        img  = center_crop(Image.open(path), WIDTH, HEIGHT, crop_h, crop_v)
        img  = draw_text_overlay(img, title, description)
        clip = make_ken_burns(img, dur_per_img, zoom_in=(i % 2 == 0))

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

    # 音声合成（ナレーション＋BGM）
    narration = narration.volumex(narr_volume)
    base_dir  = Path(config_path).parent
    bgm_full  = (base_dir / bgm_path) if bgm_path and not Path(bgm_path).is_absolute() else Path(bgm_path) if bgm_path else None
    if bgm_full and bgm_full.exists():
        print(f"Mixing BGM: {bgm_full.name}")
        bgm   = loop_bgm(str(bgm_full), total_sec, bgm_volume)
        audio = CompositeAudioClip([narration, bgm])
    else:
        if bgm_path:
            print(f"  [!] BGM not found: {bgm_path}")
        audio = narration

    video = video.set_audio(audio)

    # エクスポート
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
    config = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    generate(config)
