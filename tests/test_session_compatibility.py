from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from session_compatibility import (
    SessionChangedError,
    default_backup_root,
    repair_session,
    scan_sessions,
)


def encode(record: dict[str, object], ending: bytes = b"\n") -> bytes:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + ending


def write_session(path: Path, *, thread_id: str = "thread-1", incompatible: int = 1) -> list[bytes]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        encode(
            {
                "timestamp": "2026-08-02T07:42:41.000Z",
                "type": "session_meta",
                "payload": {"id": thread_id, "title": "跨模型测试"},
            }
        ),
        encode(
            {
                "timestamp": "2026-08-02T07:42:42.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "必须原样保留"}],
                },
            },
            b"\r\n",
        ),
        encode(
            {
                "timestamp": "2026-08-02T07:42:43.000Z",
                "type": "response_item",
                "payload": {
                    "type": "reasoning",
                    "content": [],
                },
            }
        ),
    ]
    for index in range(incompatible):
        lines.append(
            encode(
                {
                    "timestamp": f"2026-08-02T07:42:{44 + index:02d}.000Z",
                    "type": "response_item",
                    "payload": {
                        "type": "reasoning",
                        "id": f"rs-{index}",
                        "content": [{"type": "reasoning_text", "text": "private"}],
                    },
                }
            )
        )
    path.write_bytes(b"".join(lines))
    return lines


class ScannerTests(unittest.TestCase):
    def test_scan_finds_only_nonempty_reasoning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_session(root / "sessions" / "candidate.jsonl", incompatible=2)
            write_session(root / "sessions" / "clean.jsonl", thread_id="clean", incompatible=0)

            candidates = scan_sessions(root)

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].thread_id, "thread-1")
            self.assertEqual(candidates[0].title, "跨模型测试")
            self.assertEqual(candidates[0].group, "sessions")
            self.assertEqual(candidates[0].incompatible_count, 2)

    def test_scan_includes_archived_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_session(root / "archived_sessions" / "archived.jsonl", thread_id="archived")

            candidates = scan_sessions(root)

            self.assertEqual([(item.thread_id, item.group) for item in candidates], [("archived", "archived_sessions")])


class RepairTests(unittest.TestCase):
    def test_repair_clears_targets_preserves_other_lines_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "codex"
            session = root / "sessions" / "candidate.jsonl"
            original_lines = write_session(session, incompatible=2)
            candidate = scan_sessions(root)[0]
            backup_directory = Path(temp) / "backups"

            result = repair_session(candidate, backup_directory=backup_directory)

            repaired_lines = session.read_bytes().splitlines(keepends=True)
            self.assertEqual(result.modified_count, 2)
            self.assertEqual(repaired_lines[0], original_lines[0])
            self.assertEqual(repaired_lines[1], original_lines[1])
            self.assertEqual(repaired_lines[2], original_lines[2])
            for line in repaired_lines[3:]:
                self.assertEqual(json.loads(line)["payload"]["content"], [])
            self.assertIsNotNone(result.backup_path)
            assert result.backup_path is not None
            self.assertEqual(result.backup_path.read_bytes(), b"".join(original_lines))

    def test_repair_without_backup_creates_no_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "codex"
            session = root / "sessions" / "candidate.jsonl"
            write_session(session)
            candidate = scan_sessions(root)[0]

            result = repair_session(candidate, backup_directory=None)

            self.assertIsNone(result.backup_path)
            self.assertEqual(result.modified_count, 1)

    def test_repair_rejects_file_changed_after_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "codex"
            session = root / "sessions" / "candidate.jsonl"
            write_session(session)
            candidate = scan_sessions(root)[0]
            with session.open("ab") as handle:
                handle.write(encode({"type": "event_msg", "payload": {"type": "new"}}))

            with self.assertRaises(SessionChangedError):
                repair_session(candidate, backup_directory=None)

            self.assertIn(b'"type":"reasoning_text"', session.read_bytes())


class DefaultsTests(unittest.TestCase):
    def test_default_backup_root_prefers_d_drive_when_available(self) -> None:
        self.assertEqual(default_backup_root(drive_exists=lambda path: path == Path("D:/")), Path("D:/codex/backups"))


if __name__ == "__main__":
    unittest.main()
