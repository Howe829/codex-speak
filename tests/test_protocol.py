import json
import unittest

from codex_speak.protocol import Announcement, extract_announcement


def marker(status: str, speech_text: str) -> str:
    payload = json.dumps(
        {"status": status, "speech_text": speech_text},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"<!-- codex-voice-notifier:v1 {payload} -->"


class ProtocolTests(unittest.TestCase):
    def test_accepts_all_important_statuses(self) -> None:
        for status in ("completed", "blocked", "action_required"):
            with self.subTest(status=status):
                message = f"Visible answer\n\n{marker(status, '任务状态已更新。')}"
                self.assertEqual(
                    extract_announcement(message),
                    Announcement(status=status, speech_text="任务状态已更新。"),
                )

    def test_silent_requires_empty_text_and_never_returns_speech(self) -> None:
        self.assertEqual(
            extract_announcement(marker("silent", "")),
            Announcement(status="silent", speech_text=""),
        )
        self.assertIsNone(extract_announcement(marker("silent", "不要播放")))

    def test_rejects_missing_unknown_extra_and_non_trailing_markers(self) -> None:
        self.assertIsNone(extract_announcement(None))
        self.assertIsNone(extract_announcement("ordinary answer"))
        self.assertIsNone(extract_announcement(marker("unknown", "text")))
        extra = '<!-- codex-voice-notifier:v1 {"status":"completed","speech_text":"ok","extra":1} -->'
        self.assertIsNone(extract_announcement(extra))
        self.assertIsNone(extract_announcement(marker("completed", "ok") + "\nmore text"))

    def test_rejects_unhashable_status_values_without_raising(self) -> None:
        for status in (["completed"], {"name": "completed"}):
            with self.subTest(status=status):
                payload = json.dumps(
                    {"status": status, "speech_text": "任务状态已更新。"},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                message = f"<!-- codex-voice-notifier:v1 {payload} -->"
                try:
                    result = extract_announcement(message)
                except TypeError as error:
                    self.fail(f"unhashable status raised TypeError: {error}")
                self.assertIsNone(result)

    def test_sanitizes_markdown_urls_paths_controls_and_whitespace(self) -> None:
        speech = "完成 **修复**。详情 https://example.com/x，文件 /Users/howard/project/a.py。\x00  下一步运行测试。"
        result = extract_announcement(marker("completed", speech))
        self.assertEqual(
            result,
            Announcement(
                status="completed",
                speech_text="完成 修复。详情 链接，文件 相关文件。 下一步运行测试。",
            ),
        )

    def test_sanitizes_markdown_to_plain_prose(self) -> None:
        speech = (
            "> - **完成** [修复](https://example.com/fix)\n"
            "> 1. 移除 ![截图](/Users/howard/screenshot.png) 与 ~~旧方案~~。"
        )
        self.assertEqual(
            extract_announcement(marker("completed", speech)),
            Announcement(
                status="completed",
                speech_text="完成 修复 移除 截图 与 旧方案。",
            ),
        )

    def test_controls_cannot_bypass_markdown_recognition(self) -> None:
        speech = "完成 [修复]\u200b(https://example.com/fix)。"
        self.assertEqual(
            extract_announcement(marker("completed", speech)),
            Announcement(status="completed", speech_text="完成 修复。"),
        )

    def test_cr_separated_blockquote_lists_are_plain_prose(self) -> None:
        speech = "> - 第一项\r> 1. 第二项。"
        self.assertEqual(
            extract_announcement(marker("completed", speech)),
            Announcement(status="completed", speech_text="第一项 第二项。"),
        )

    def test_redacts_root_level_absolute_paths(self) -> None:
        speech = "密钥位于 /secret，令牌位于 /token。"
        self.assertEqual(
            extract_announcement(marker("completed", speech)),
            Announcement(
                status="completed",
                speech_text="密钥位于 相关文件，令牌位于 相关文件。",
            ),
        )

    def test_removes_unicode_control_and_format_characters(self) -> None:
        speech = "完成\u202e\u200b修复，保留中文与🙂。"
        self.assertEqual(
            extract_announcement(marker("completed", speech)),
            Announcement(
                status="completed",
                speech_text="完成修复，保留中文与🙂。",
            ),
        )

    def test_truncates_at_last_sentence_boundary_within_280_characters(self) -> None:
        speech = "甲" * 150 + "。" + "乙" * 150 + "。" + "丙" * 20
        result = extract_announcement(marker("completed", speech))
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result.speech_text), 151)
        self.assertTrue(result.speech_text.endswith("。"))

    def test_hard_cuts_when_no_sentence_boundary_exists(self) -> None:
        result = extract_announcement(marker("completed", "甲" * 400))
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result.speech_text), 280)

    def test_preserves_exact_limit_and_hard_cuts_one_character_over(self) -> None:
        exact = extract_announcement(marker("completed", "甲" * 280))
        over = extract_announcement(marker("completed", "乙" * 281))
        self.assertEqual(
            exact,
            Announcement(status="completed", speech_text="甲" * 280),
        )
        self.assertEqual(
            over,
            Announcement(status="completed", speech_text="乙" * 280),
        )

    def test_shell_metacharacters_remain_plain_text(self) -> None:
        speech = "完成；$(touch /tmp/pwned)；rm -rf ~"
        result = extract_announcement(marker("completed", speech))
        self.assertEqual(
            result,
            Announcement(
                status="completed",
                speech_text="完成；$(touch 相关文件)；rm -rf ~",
            ),
        )


if __name__ == "__main__":
    unittest.main()
