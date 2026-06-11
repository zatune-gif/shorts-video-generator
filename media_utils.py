"""app.py / generate_video.py 共通のメディア処理ユーティリティ。

ルビ除去・クロップ・VOICEVOX合成は両スクリプトで同一処理のため、ここに一元化する。
"""

import json
import re

import requests
from PIL import Image

VOICEVOX_URL          = "http://localhost:50021"
OUTPUT_SAMPLING_RATE  = 44100
VOICEVOX_PING_TIMEOUT = 2


def strip_ruby(text: str) -> str:
    """{漢字|よみ} 記法を読み仮名のみに変換して返す"""
    return re.sub(r'\{([^|{}]+)\|([^|{}]+)\}', r'\2', text)


def crop_with_offset(img: Image.Image, w: int, h: int,
                     h_offset: int = 0, v_offset: int = 0) -> Image.Image:
    """
    縦横比を保ちながらクロップしてリサイズ。
    h_offset: -100〜+100（負=左寄り、正=右寄り）横長画像に有効
    v_offset: -100〜+100（負=上寄り、正=下寄り）縦長画像に有効
    """
    img = img.convert("RGB")
    sw, sh = img.size
    if sw / sh > w / h:
        # 横長：左右をクロップ
        nw     = int(sh * w / h)
        margin = (sw - nw) // 2
        shift  = int(margin * h_offset / 100)
        x0     = max(0, min(margin + shift, sw - nw))
        img    = img.crop((x0, 0, x0 + nw, sh))
    else:
        # 縦長：上下をクロップ
        nh     = int(sw * h / w)
        margin = (sh - nh) // 2
        shift  = int(margin * v_offset / 100)
        y0     = max(0, min(margin + shift, sh - nh))
        img    = img.crop((0, y0, sw, y0 + nh))
    return img.resize((w, h), Image.LANCZOS)


def voicevox_available() -> bool:
    try:
        return requests.get(f"{VOICEVOX_URL}/version",
                            timeout=VOICEVOX_PING_TIMEOUT).ok
    except Exception:
        return False


def synthesize_voicevox(text: str, speaker_id: int,
                        speed: float, pitch: float) -> bytes:
    """VOICEVOXでテキストを合成しWAVバイト列を返す（audio_query → synthesis）"""
    r = requests.post(f"{VOICEVOX_URL}/audio_query",
                      params={"text": text, "speaker": speaker_id})
    r.raise_for_status()
    query = r.json()
    query["speedScale"]         = speed
    query["pitchScale"]         = pitch
    query["outputSamplingRate"] = OUTPUT_SAMPLING_RATE

    r = requests.post(f"{VOICEVOX_URL}/synthesis",
                      headers={"Content-Type": "application/json"},
                      params={"speaker": speaker_id},
                      data=json.dumps(query))
    r.raise_for_status()
    return r.content
