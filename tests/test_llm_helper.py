import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from llm_helper import generate_video_metadata


class TestGenerateVideoMetadata:
    def test_returns_dict_with_title_and_description(self):
        mock_response = "タイトル: テストタイトル\n説明文: テスト説明文"
        with patch("llm_helper.LLMClient") as mock_cls:
            mock_cls.return_value.generate.return_value = mock_response
            result = generate_video_metadata("テストナレーション")

        assert "title" in result
        assert "description" in result
        assert result["title"] == "テストタイトル"
        assert result["description"] == "テスト説明文"

    def test_returns_empty_strings_when_llm_unavailable(self):
        from shared.llm_client import LLMUnavailableError
        with patch("llm_helper.LLMClient") as mock_cls:
            mock_cls.return_value.generate.side_effect = LLMUnavailableError("unavailable")
            result = generate_video_metadata("テストナレーション")

        assert result == {"title": "", "description": ""}

    def test_empty_narration_still_returns_dict(self):
        mock_response = "タイトル: デフォルトタイトル\n説明文: デフォルト説明"
        with patch("llm_helper.LLMClient") as mock_cls:
            mock_cls.return_value.generate.return_value = mock_response
            result = generate_video_metadata("")

        assert isinstance(result, dict)
        assert "title" in result
        assert "description" in result
