from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def encode(record: dict[str, object]) -> bytes:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: exe_fixture.py PATH_TO_EXE")
    executable = Path(sys.argv[1]).resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)

    with tempfile.TemporaryDirectory() as temp:
        temp_root = Path(temp)
        codex_root = temp_root / "codex"
        session = codex_root / "sessions" / "fixture.jsonl"
        session.parent.mkdir(parents=True)
        meta = encode(
            {
                "timestamp": "2026-08-08T01:00:00Z",
                "type": "session_meta",
                "payload": {"id": "fixture-thread", "title": "EXE fixture"},
            }
        )
        user = encode(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "preserve exactly"}],
                },
            }
        )
        reasoning = encode(
            {
                "type": "response_item",
                "payload": {
                    "type": "reasoning",
                    "content": [{"type": "reasoning_text", "text": "private"}],
                },
            }
        )
        web_search = encode(
            {
                "type": "response_item",
                "payload": {
                    "type": "web_search_call",
                    "id": "call_00_fixture",
                    "status": "completed",
                    "action": {"type": "search", "query": "fixture"},
                },
            }
        )
        session.write_bytes(meta + user + reasoning + web_search)
        backup_root = temp_root / "backups"
        log_root = temp_root / "logs"

        environment = os.environ.copy()
        environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [
                str(executable),
                "--codex-root",
                str(codex_root),
                "--backup-root",
                str(backup_root),
                "--log-root",
                str(log_root),
                "--no-pause",
            ],
            input="1\n2\nAPPLY-NO-BACKUP\n",
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env=environment,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"EXE failed ({result.returncode})\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

        repaired = session.read_bytes().splitlines(keepends=True)
        if repaired[0] != meta or repaired[1] != user:
            raise AssertionError("EXE changed a non-target record")
        if json.loads(repaired[2])["payload"]["content"] != []:
            raise AssertionError("EXE did not clear incompatible reasoning content")
        if json.loads(repaired[3])["payload"]["id"] != "ws_00_fixture":
            raise AssertionError("EXE did not convert incompatible web search ID")
        if backup_root.exists():
            raise AssertionError("no-backup mode created a backup directory")
        if len(list(log_root.glob("*.log"))) != 1:
            raise AssertionError("EXE did not create exactly one log")

    print("PASS: standalone EXE repairs fixture without Python on PATH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
