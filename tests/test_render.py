import unittest

from codex_speak.protocol import ParsedResponse
from codex_speak.render import (
    SpeechPayload,
    normalize_full_text,
    render_speech,
    segment_text,
)


class RenderTests(unittest.TestCase):
    def test_modes(self) -> None:
        silent = ParsedResponse("silent", "", "普通回答")
        done = ParsedResponse("completed", "任务完成。", "长正文")
        self.assertIsNone(render_speech(silent, "summary"))
        self.assertEqual(
            render_speech(done, "summary"),
            SpeechPayload("summary", "completed", ("任务完成。",)),
        )
        self.assertEqual(
            render_speech(silent, "full"),
            SpeechPayload("full", "silent", ("普通回答",)),
        )

    def test_summarizes_non_prose(self) -> None:
        inline = chr(96) + "x=1" + chr(96)
        fence = chr(96) * 3
        body = (
            "# 标题\n[文档](https://example.com) "
            + inline
            + "\n"
            + fence
            + "py\nprint(1)\n"
            + fence
            + "\n/Users/a/f"
        )
        payload = render_speech(ParsedResponse("silent", "", body), "full")
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertIn("标题", payload.segments[0])
        self.assertIn("链接", payload.segments[0])
        self.assertIn("代码", payload.segments[0])
        self.assertIn("相关文件", payload.segments[0])

    def test_normalizes_images_urls_tables_emphasis_and_controls(self) -> None:
        body = (
            "\u202e## **进度**\n"
            "![截图](/private/a.png) https://example.com/x\n"
            "| 项目 | 状态 |\n| --- | --- |\n| A | ✅ |\n"
            "家目录 ~/secret 与 *重点*。"
        )
        normalized = normalize_full_text(body)
        self.assertNotIn("\u202e", normalized)
        self.assertNotIn("https://", normalized)
        self.assertNotIn("/private/a.png", normalized)
        self.assertNotIn("~/secret", normalized)
        self.assertNotIn("|", normalized)
        self.assertIn("图片", normalized)
        self.assertIn("链接", normalized)
        self.assertIn("相关文件", normalized)
        self.assertIn("进度", normalized)
        self.assertIn("A ✅", normalized)

    def test_removes_double_quote_delimiters_without_dropping_content(self) -> None:
        body = "新增内部心跳，watchdog 现在能区分“现场断流”和“转写进程卡死”。"
        self.assertEqual(
            normalize_full_text(body),
            "新增内部心跳，watchdog 现在能区分现场断流和转写进程卡死。",
        )

    def test_removes_supported_double_quotes_but_keeps_single_quotes(self) -> None:
        cases = {
            '前文 "ASCII label" 后文': "前文 ASCII label 后文",
            "前文 „low quote‟ 后文": "前文 low quote 后文",
            "前文 ＂全角内容＂ 后文": "前文 全角内容 后文",
            "前文 'single quote' 后文": "前文 'single quote' 后文",
            "前文 “unbalanced 后文": "前文 unbalanced 后文",
        }
        for body, expected in cases.items():
            with self.subTest(body=body):
                self.assertEqual(normalize_full_text(body), expected)

    def test_fenced_code_and_image_alt_use_exact_spoken_placeholders(self) -> None:
        body = "![订单截图](/private/order.png)\n```python\nsecret = 1\n```"
        self.assertEqual(normalize_full_text(body), "订单截图 图片 代码块")
        self.assertEqual(normalize_full_text("![](/private/empty.png)"), "图片")

    def test_normalizes_four_backtick_fence(self) -> None:
        body = "前文\n````python\nx = 1\n````\n后文"
        self.assertEqual(normalize_full_text(body), "前文 代码块 后文")

    def test_normalizes_fence_closed_by_longer_matching_delimiter(self) -> None:
        cases = (
            "前文\n```python\nx = 1\n````\n后文",
            "前文\n~~~python\nx = 1\n~~~~\n后文",
        )
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(normalize_full_text(body), "前文 代码块 后文")

    def test_does_not_match_mismatched_fence_delimiters(self) -> None:
        body = "前文\n```python\nx = 1\n~~~\n后文"
        self.assertEqual(
            normalize_full_text(body),
            "前文 ```python x = 1 ~ 后文",
        )

    def test_normalizes_matching_multi_backtick_inline_code(self) -> None:
        body = "前文 ``x = `tick` `` 后文"
        self.assertEqual(normalize_full_text(body), "前文 代码 后文")

    def test_preserves_short_prose_labels_in_single_backticks(self) -> None:
        body = "模式为 `Full`、`Summary`、`codex-speak`、`语音模式` 和 `two words`。"
        self.assertEqual(
            normalize_full_text(body),
            "模式为 Full、Summary、codex-speak、语音模式 和 two words。",
        )

    def test_replaces_code_shaped_and_ambiguous_inline_spans(self) -> None:
        cases = (
            "`x=1`",
            "`run()`",
            "`~/secret`",
            "`a | b`",
            "`" + "a" * 33 + "`",
            "``plain label``",
        )
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(normalize_full_text(body), "代码")

    def test_classifies_original_inline_content_before_normalizing_it(self) -> None:
        cases = (
            '`"secret"`',
            "`“secret”`",
            "`[label](https://example.com)`",
            "`![image](/private/image.png)`",
            "`snake_case`",
        )
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(normalize_full_text(body), "代码")

    def test_replaces_complete_home_relative_path(self) -> None:
        body = "查看 ~/secret/file.txt 获取详情"
        self.assertEqual(normalize_full_text(body), "查看 相关文件 获取详情")

    def test_empty_full_body_returns_none(self) -> None:
        self.assertIsNone(render_speech(ParsedResponse("silent", "", " \n\t"), "full"))

    def test_segments_without_loss(self) -> None:
        text = "甲。" * 700
        payload = render_speech(ParsedResponse("silent", "", text), "full")
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertTrue(all(1 <= len(part) <= 600 for part in payload.segments))
        self.assertEqual("".join(payload.segments), text)

    def test_segment_boundaries_and_hard_split(self) -> None:
        self.assertEqual(segment_text("甲" * 600), ("甲" * 600,))
        self.assertEqual(segment_text("甲" * 601), ("甲" * 600, "甲"))

        sentence = "甲" * 590 + "。" + "乙" * 20
        self.assertEqual(segment_text(sentence), (sentence[:591], sentence[591:]))

        paragraph = "甲" * 300 + "\n\n" + "乙" * 300
        parts = segment_text(paragraph)
        self.assertEqual(parts, (paragraph[:302], paragraph[302:]))
        self.assertEqual("".join(parts), paragraph)

    def test_ignores_partial_paragraph_boundary_at_limit(self) -> None:
        text = "甲" * 100 + "\n\n" + "乙" * 497 + "\n\n" + "丙" * 20
        parts = segment_text(text)
        self.assertEqual(parts[0], text[:102])
        self.assertEqual("".join(parts), text)

    def test_preserves_emoji(self) -> None:
        payload = render_speech(ParsedResponse("silent", "", "完成 ✅🙂"), "full")
        self.assertEqual(payload, SpeechPayload("full", "silent", ("完成 ✅🙂",)))

    def test_rejects_unknown_mode(self) -> None:
        with self.assertRaises(ValueError):
            render_speech(ParsedResponse("silent", "", "正文"), "other")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
