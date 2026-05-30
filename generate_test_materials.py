#!/usr/bin/env python3
"""テスト素材生成スクリプト（画像3枚・ナレーション・BGM）"""

import wave
from pathlib import Path

import numpy as np
import pyttsx3
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "C:/Windows/Fonts/meiryo.ttc"
WIDTH, HEIGHT = 1080, 1920
SR = 44100


# ── 画像生成 ─────────────────────────────────────────────

def make_gradient_image(path, color1, color2, label):
    t = np.linspace(0, 1, HEIGHT).reshape(-1, 1)
    r = (color1[0] * (1 - t) + color2[0] * t).astype(np.uint8)
    g = (color1[1] * (1 - t) + color2[1] * t).astype(np.uint8)
    b = (color1[2] * (1 - t) + color2[2] * t).astype(np.uint8)
    arr = np.stack(
        [np.tile(r, (1, WIDTH)), np.tile(g, (1, WIDTH)), np.tile(b, (1, WIDTH))],
        axis=2,
    )
    img = Image.fromarray(arr)

    # 半透明の装飾円
    cx, cy = WIDTH // 2, HEIGHT // 2
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for radius, alpha in [(400, 25), (280, 35), (160, 50), (80, 70)]:
        od.ellipse(
            [(cx - radius, cy - radius), (cx + radius, cy + radius)],
            outline=(255, 255, 255, alpha),
            width=3,
        )
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)
    try:
        font_lg = ImageFont.truetype(FONT_PATH, 110)
        font_sm = ImageFont.truetype(FONT_PATH, 52)
    except OSError:
        font_lg = font_sm = ImageFont.load_default()

    for dx, dy, color in [(4, 4, (0, 0, 0)), (0, 0, (255, 255, 255))]:
        draw.text((cx + dx, cy - 60 + dy), label,              font=font_lg, fill=color, anchor="mm")
        draw.text((cx + dx, cy + 80 + dy), "AI Generated Art", font=font_sm, fill=color, anchor="mm")

    img.save(path)
    print(f"  [image] {path}")


# ── ナレーション生成（Windows TTS） ──────────────────────

NARRATION_TEXT = (
    "こんにちは。今回はAIで生成した幻想的な風景作品シリーズをご紹介します。"
    "作品01は、紫と青のグラデーションが美しい宇宙的な風景です。"
    "作品02は、オレンジと赤のあたたかな夕焼けをイメージしました。"
    "作品03は、緑と青の清涼感ある自然の風景です。"
    "ぜひお楽しみください。"
)


def make_narration(path):
    engine = pyttsx3.init()

    # 日本語ボイスを選択
    for voice in engine.getProperty("voices"):
        if "ja" in voice.id.lower() or "japanese" in voice.name.lower():
            engine.setProperty("voice", voice.id)
            break

    engine.setProperty("rate", 135)    # 読み上げ速度（デフォルト200）
    engine.setProperty("volume", 0.95) # 音量

    engine.save_to_file(NARRATION_TEXT, str(path))
    engine.runAndWait()
    print(f"  [narr]  {path}")


# ── BGM生成（ピアノ風アルペジオ＋倍音） ─────────────────

def piano_tone(freq: float, dur: float) -> np.ndarray:
    """倍音付きピアノ音（波形1音分）"""
    n   = int(SR * dur)
    t   = np.arange(n) / SR
    harmonics = [(1, 1.0), (2, 0.55), (3, 0.30), (4, 0.15), (6, 0.06), (8, 0.03)]
    wave  = sum(a * np.sin(2 * np.pi * h * freq * t) for h, a in harmonics)
    wave /= sum(a for _, a in harmonics)   # 正規化
    # ピアノ型エンベロープ（素早いアタック、指数減衰）
    attack = int(0.008 * SR)
    env    = np.exp(-3.5 * t / dur)
    env[:attack] *= np.linspace(0, 1, attack) / env[:attack].clip(min=1e-9)
    return wave * env


def make_bgm(path, duration=40):
    """Cメジャーのアルペジオ BGM"""
    # C-Am-F-G コード進行（各2小節）
    chord_sequence = [
        [261.6, 329.6, 392.0, 523.2],   # C  major
        [220.0, 277.2, 329.6, 440.0],   # A  minor
        [174.6, 220.0, 261.6, 349.2],   # F  major
        [196.0, 246.9, 293.7, 392.0],   # G  major
    ]
    note_dur   = 0.32   # 1音の長さ (秒)
    note_vol   = 0.28   # 音量

    signal = np.zeros(int(SR * duration))

    note_idx = 0
    t_pos    = 0.0
    while t_pos < duration:
        chord = chord_sequence[(note_idx // len(chord_sequence[0])) % len(chord_sequence)]
        note  = chord[note_idx % len(chord)]

        start = int(t_pos * SR)
        tone  = piano_tone(note, note_dur) * note_vol
        end   = min(start + len(tone), len(signal))
        signal[start:end] += tone[:end - start]

        t_pos    += note_dur
        note_idx += 1

    # 全体フェードアウト
    fade = int(SR * 2.5)
    signal[-fade:] *= np.linspace(1, 0, fade)

    samples = np.clip(signal, -1.0, 1.0)
    samples = (samples * 32767).astype(np.int16)
    with wave.open(str(path), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SR)
        wav.writeframes(samples.tobytes())
    print(f"  [bgm]   {path}  ({duration}s)")


# ── メイン ───────────────────────────────────────────────

def main():
    base    = Path(__file__).parent
    img_dir = base / "input" / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    print("=== 画像生成 ===")
    make_gradient_image(img_dir / "01.png", (70, 30, 160), (170, 80, 230), "作品 01")
    make_gradient_image(img_dir / "02.png", (170, 50, 30), (235, 130, 80), "作品 02")
    make_gradient_image(img_dir / "03.png", (20, 110, 90),  (80, 200, 165), "作品 03")

    print("\n=== ナレーション生成（日本語TTS） ===")
    make_narration(base / "input" / "narration.wav")

    print("\n=== BGM生成 ===")
    make_bgm(base / "input" / "bgm.wav", duration=40)

    print("\n完了！ python generate_video.py で動画を生成してください。")


if __name__ == "__main__":
    main()
