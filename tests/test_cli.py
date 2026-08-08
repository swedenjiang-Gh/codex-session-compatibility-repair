from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest

import compatibility_repair_cli as cli


def encode(record: dict[str, object]) -> bytes:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def create_candidate(root: Path, thread_id: str = "thread-1") -> Path:
    path = root / "sessions" / f"{thread_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        encode({"timestamp": "2026-08-08T01:00:00Z", "type": "session_meta", "payload": {"id": thread_id, "title": "测试任务"}})
        + encode({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "keep"}]}})
        + encode({"type": "response_item", "payload": {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "private"}]}})
    )
    return path


class SelectionTests(unittest.TestCase):
    def test_parse_selection_accepts_multiple_numbers_and_all(self) -> None:
        self.assertEqual(cli.parse_selection("3, 1", 3), [0, 2])
        self.assertEqual(cli.parse_selection("ALL", 3), [0, 1, 2])

    def test_parse_selection_rejects_out_of_range_number(self) -> None:
        with self.assertRaises(ValueError):
            cli.parse_selection("4", 3)

    def test_parser_accepts_isolated_backup_and_log_roots(self) -> None:
        arguments = cli.build_parser().parse_args(
            ["--codex-root", "C:/fixture", "--backup-root", "D:/backup", "--log-root", "D:/log"]
        )

        self.assertEqual(arguments.codex_root, Path("C:/fixture"))
        self.assertEqual(arguments.backup_root, Path("D:/backup"))
        self.assertEqual(arguments.log_root, Path("D:/log"))


class ProcessTests(unittest.TestCase):
    def test_tasklist_parser_returns_all_codex_process_names(self) -> None:
        tasklist = (
            '"ChatGPT.exe","100","Console","1","10,000 K"\n'
            '"codex.exe","101","Console","1","10,000 K"\n'
            '"codex-code-mode-host.exe","102","Console","1","10,000 K"\n'
            '"notepad.exe","103","Console","1","10,000 K"\n'
        )
        self.assertEqual(
            cli.codex_processes_from_tasklist(tasklist),
            ["ChatGPT.exe", "codex-code-mode-host.exe", "codex.exe"],
        )

    def test_wait_rechecks_until_processes_exit(self) -> None:
        states = iter([["ChatGPT.exe"], ["codex.exe"], []])
        sleeps: list[float] = []

        result = cli.wait_for_codex_exit(
            process_checker=lambda: next(states),
            sleep_fn=sleeps.append,
            timeout_seconds=10,
            monotonic_values=iter([0.0, 1.0, 2.0]),
        )

        self.assertTrue(result)
        self.assertEqual(sleeps, [2.0, 2.0])

    def test_wait_returns_false_at_timeout(self) -> None:
        result = cli.wait_for_codex_exit(
            process_checker=lambda: ["ChatGPT.exe"],
            sleep_fn=lambda _: None,
            timeout_seconds=10,
            monotonic_values=iter([0.0, 11.0]),
        )
        self.assertFalse(result)


class InteractiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "codex"
        self.session = create_candidate(self.root)
        self.backup_root = Path(self.temp.name) / "backups"
        self.log_root = Path(self.temp.name) / "logs"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, answers: list[str], processes: list[list[str]] | None = None) -> tuple[int, str]:
        answer_iterator = iter(answers)
        process_iterator = iter(processes or [[]])
        output = io.StringIO()
        result = cli.run_interactive(
            self.root,
            input_fn=lambda _prompt: next(answer_iterator),
            output_fn=lambda message="": print(message, file=output),
            process_checker=lambda: next(process_iterator, []),
            sleep_fn=lambda _seconds: None,
            monotonic_values=iter([0.0, 1.0, 2.0, 3.0]),
            backup_root=self.backup_root,
            log_root=self.log_root,
        )
        return result, output.getvalue()

    def reasoning_content(self) -> list[object]:
        records = [json.loads(line) for line in self.session.read_text(encoding="utf-8").splitlines()]
        return records[-1]["payload"]["content"]

    def test_no_backup_requires_apply_no_backup(self) -> None:
        result, output = self.run_cli(["1", "2", "APPLY"])

        self.assertEqual(result, 0)
        self.assertIn("已取消", output)
        self.assertTrue(self.reasoning_content())
        self.assertFalse(self.backup_root.exists())

    def test_no_backup_mode_repairs_without_creating_backup_directory(self) -> None:
        result, output = self.run_cli(["1", "2", "APPLY-NO-BACKUP"])

        self.assertEqual(result, 0)
        self.assertIn("修复完成", output)
        self.assertEqual(self.reasoning_content(), [])
        self.assertFalse(self.backup_root.exists())
        self.assertEqual(len(list(self.log_root.glob("*.log"))), 1)

    def test_backup_mode_waits_then_repairs_and_preserves_original(self) -> None:
        original = self.session.read_bytes()

        result, output = self.run_cli(
            ["ALL", "1", "APPLY"],
            processes=[["ChatGPT.exe"], []],
        )

        self.assertEqual(result, 0)
        self.assertIn("等待 Codex", output)
        self.assertEqual(self.reasoning_content(), [])
        backups = list(self.backup_root.rglob("*.jsonl"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
