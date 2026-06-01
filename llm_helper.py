import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.llm_client import LLMClient, LLMUnavailableError


def generate_video_metadata(narration_text: str) -> dict:
    """ナレーション台本からタイトルと説明文を生成する"""
    llm = LLMClient()
    prompt = f"""以下のナレーション台本からYouTube Shortsのタイトルと説明文を日本語で生成してください。

【台本】
{narration_text}

【出力形式】必ず以下の形式で出力してください
タイトル: （30文字以内で魅力的なタイトル）
説明文: （50文字以内の簡潔な説明）"""

    try:
        response = llm.generate(prompt)
        title = ""
        description = ""
        for line in response.strip().splitlines():
            if line.startswith("タイトル:"):
                title = line.replace("タイトル:", "").strip()
            elif line.startswith("説明文:"):
                description = line.replace("説明文:", "").strip()
        return {"title": title, "description": description}
    except LLMUnavailableError:
        return {"title": "", "description": ""}
