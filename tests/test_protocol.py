import json
import unittest

from codex_speak.protocol import ParsedResponse, extract_response


def marker(status: str, text: str) -> str:
    payload = json.dumps(
        {"status": status, "speech_text": text},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"<!-- codex-speak:v1 {payload} -->"


class ProtocolTests(unittest.TestCase):
    def test_extracts_body_and_summary(self) -> None:
        parsed = extract_response("可见正文\n\n" + marker("completed", "任务完成。"))
        self.assertEqual(parsed, ParsedResponse("completed", "任务完成。", "可见正文"))

    def test_accepts_all_important_statuses(self) -> None:
        for status in ("completed", "blocked", "action_required"):
            with self.subTest(status=status):
                self.assertEqual(
                    extract_response(marker(status, "任务状态已更新。")),
                    ParsedResponse(status, "任务状态已更新。", ""),
                )

    def test_silent_requires_empty_text(self) -> None:
        self.assertEqual(
            extract_response(marker("silent", "")),
            ParsedResponse("silent", "", ""),
        )
        self.assertIsNone(extract_response(marker("silent", "不要播放")))

    def test_rejects_legacy_duplicate_and_non_trailing(self) -> None:
        legacy = '<!-- codex-voice-notifier:v1 {"status":"silent","speech_text":""} -->'
        self.assertIsNone(extract_response(legacy))
        self.assertIsNone(extract_response(marker("silent", "") * 2))
        self.assertIsNone(extract_response(marker("silent", "") + " trailing"))

    def test_rejects_missing_unknown_extra_and_invalid_payloads(self) -> None:
        self.assertIsNone(extract_response(None))
        self.assertIsNone(extract_response("ordinary answer"))
        self.assertIsNone(extract_response(marker("unknown", "text")))
        extra = '<!-- codex-speak:v1 {"status":"completed","speech_text":"ok","extra":1} -->'
        self.assertIsNone(extract_response(extra))
        missing = '<!-- codex-speak:v1 {"status":"completed"} -->'
        self.assertIsNone(extract_response(missing))
        malformed = '<!-- codex-speak:v1 {not-json} -->'
        self.assertIsNone(extract_response(malformed))

    def test_rejects_unhashable_status_values_without_raising(self) -> None:
        for status in (["completed"], {"name": "completed"}):
            with self.subTest(status=status):
                payload = json.dumps(
                    {"status": status, "speech_text": "任务状态已更新。"},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                self.assertIsNone(extract_response(f"<!-- codex-speak:v1 {payload} -->"))

    def test_sanitizes_summary_and_preserves_visible_body(self) -> None:
        speech = "完成 **修复**。详情 https://example.com/x，文件 /Users/howard/project/a.py。\x00  下一步运行测试。"
        body = "# Markdown 正文\n\n`原样保留`"
        result = extract_response(body + "\n" + marker("completed", speech))
        self.assertEqual(
            result,
            ParsedResponse(
                "completed",
                "完成 修复。详情 链接，文件 相关文件。 下一步运行测试。",
                body,
            ),
        )

    def test_sanitizes_markdown_to_plain_prose(self) -> None:
        speech = (
            "> - **完成** [修复](https://example.com/fix)\n"
            "> 1. 移除 ![截图](/Users/howard/screenshot.png) 与 ~~旧方案~~。"
        )
        self.assertEqual(
            extract_response(marker("completed", speech)),
            ParsedResponse("completed", "完成 修复 移除 截图 与 旧方案。", ""),
        )

    def test_controls_cannot_bypass_markdown_recognition(self) -> None:
        speech = "完成 [修复]\u200b(https://example.com/fix)。"
        self.assertEqual(
            extract_response(marker("completed", speech)),
            ParsedResponse("completed", "完成 修复。", ""),
        )

    def test_truncates_summary_at_280_characters(self) -> None:
        with_boundary = "甲" * 150 + "。" + "乙" * 150 + "。" + "丙" * 20
        parsed = extract_response(marker("completed", with_boundary))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(len(parsed.summary_text), 151)
        self.assertTrue(parsed.summary_text.endswith("。"))

        exact = extract_response(marker("completed", "甲" * 280))
        over = extract_response(marker("completed", "乙" * 281))
        self.assertEqual(exact, ParsedResponse("completed", "甲" * 280, ""))
        self.assertEqual(over, ParsedResponse("completed", "乙" * 280, ""))

    def test_allows_trailing_whitespace_after_marker(self) -> None:
        self.assertEqual(
            extract_response("正文\n" + marker("completed", "完成。") + "\n\t"),
            ParsedResponse("completed", "完成。", "正文"),
        )


if __name__ == "__main__":
    unittest.main()
