from PIL import Image

from media_utils import strip_ruby, crop_with_offset


class TestStripRuby:
    def test_converts_ruby_to_reading(self):
        assert strip_ruby("{今日|きょう}は{晴れ|はれ}です") == "きょうははれです"

    def test_text_without_ruby_unchanged(self):
        assert strip_ruby("こんにちは") == "こんにちは"

    def test_empty_string(self):
        assert strip_ruby("") == ""

    def test_mixed_content(self):
        assert strip_ruby("AIで{生成|せいせい}した画像") == "AIでせいせいした画像"


class TestCropWithOffset:
    def test_landscape_to_portrait_returns_target_size(self):
        img = Image.new("RGB", (1920, 1080), "red")
        out = crop_with_offset(img, 108, 192)
        assert out.size == (108, 192)

    def test_portrait_to_portrait_returns_target_size(self):
        img = Image.new("RGB", (500, 2000), "blue")
        out = crop_with_offset(img, 108, 192)
        assert out.size == (108, 192)

    def test_offset_does_not_exceed_bounds(self):
        img = Image.new("RGB", (1920, 1080), "green")
        # 極端なオフセットでもクラッシュせず目標サイズを返す
        for offset in (-100, 100):
            out = crop_with_offset(img, 108, 192, h_offset=offset, v_offset=offset)
            assert out.size == (108, 192)

    def test_rgba_input_converted(self):
        img = Image.new("RGBA", (1000, 1000), (255, 0, 0, 128))
        out = crop_with_offset(img, 100, 100)
        assert out.mode == "RGB"
        assert out.size == (100, 100)
