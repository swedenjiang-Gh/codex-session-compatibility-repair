# Codex Session Compatibility Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish a single-file Windows EXE that safely repairs DeepSeek-to-GPT Codex session history incompatibilities while preserving visible conversation content.

**Architecture:** A standard-library Python core scans JSONL sessions and prepares byte-preserving replacements; a small interactive console frontend handles selection, backup choice, confirmation, and process waiting. PyInstaller packages the frontend as a one-file console EXE.

**Tech Stack:** Python 3.11+, standard library, `unittest`, PowerShell 7 build script, PyInstaller on GitHub Actions Windows runner, Git/GitHub CLI.

## Global Constraints

- Modify only non-empty `response_item.payload.type = "reasoning"` content arrays.
- Preserve every non-target JSONL line byte-for-byte.
- Never read or publish API keys, proxy credentials, real sessions, backups, or logs.
- Backup is user-selectable; `APPLY` confirms backup mode and `APPLY-NO-BACKUP` confirms no-backup mode.
- Wait up to 30 minutes for `ChatGPT.exe`, `codex.exe`, and `codex-code-mode-host.exe` to exit before scanning and recheck before writing.
- Do not modify `state_5.sqlite` or provider metadata.
- Publish source to public `codex-session-compatibility-repair`; do not create a GitHub Release.

---

### Task 1: Core session scanner and repair engine

**Files:**
- Create: `session_compatibility.py`
- Create: `tests/test_session_compatibility.py`

**Interfaces:**
- Produces: `SessionCandidate`, `scan_sessions(root)`, `repair_session(candidate, backup_directory)` and `default_backup_root()`.
- Consumes: JSONL files under `sessions/` and `archived_sessions/`.

- [ ] **Step 1: Write failing scanner tests**

```python
def test_scan_finds_only_nonempty_reasoning(tmp_path):
    candidate = scan_sessions(tmp_path)[0]
    assert candidate.thread_id == "thread-1"
    assert candidate.incompatible_count == 1
```

- [ ] **Step 2: Run scanner test and verify RED**

Run: `python -m unittest tests.test_session_compatibility.ScannerTests -v`

Expected: FAIL because `session_compatibility` does not exist.

- [ ] **Step 3: Implement minimal scanner**

Parse every JSONL line, derive the thread ID from `session_meta.payload.id`, derive title/date when available, and count only non-empty reasoning content arrays.

- [ ] **Step 4: Write failing repair tests**

```python
def test_repair_clears_targets_and_preserves_other_lines(tmp_path):
    result = repair_session(candidate, backup_directory=backup_dir)
    assert result.modified_count == 1
    assert repaired_lines[1] == original_user_line
    assert backup_path.read_bytes() == original_bytes
```

Also test no-backup mode, changed-source rejection, invalid JSON rejection, line-count preservation, and zero-target rejection.

- [ ] **Step 5: Implement safe repair**

Re-read the source, validate size/mtime/SHA-256/count, copy and hash-check the optional backup, write a sibling temporary file, validate all records, then call `os.replace`.

- [ ] **Step 6: Run core tests and verify GREEN**

Run: `python -m unittest tests.test_session_compatibility -v`

Expected: all core tests PASS.

- [ ] **Step 7: Commit core**

```powershell
git add session_compatibility.py tests/test_session_compatibility.py
git commit -m "feat: add safe session compatibility repair engine"
```

### Task 2: Interactive double-click console workflow

**Files:**
- Create: `compatibility_repair_cli.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 1 APIs.
- Produces: `run_interactive(...)`, `parse_selection(...)`, `running_codex_processes()`, `wait_for_codex_exit(...)`, and `main()`.

- [ ] **Step 1: Write failing selection and confirmation tests**

```python
def test_no_backup_requires_strong_confirmation():
    result = run_cli(["1", "2", "APPLY"])
    assert result == 0
    assert "已取消" in output
```

Cover one/multiple selections, `ALL`, invalid selection, cancel, backup confirmation, no-backup confirmation, and empty candidate list.

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `python -m unittest tests.test_cli -v`

Expected: FAIL because the CLI module does not exist.

- [ ] **Step 3: Implement selection and preview**

Render numbered candidates; request selection, backup mode, and exact confirmation token before any process wait or write.

- [ ] **Step 4: Write failing process-wait tests**

```python
def test_wait_rechecks_until_processes_exit():
    states = iter([["ChatGPT.exe"], []])
    assert wait_for_codex_exit(lambda: next(states), sleep_fn=lambda _: None, timeout=5)
```

Include timeout behavior and recognition of all three process names.

- [ ] **Step 5: Implement process waiting and result reporting**

Poll every two seconds for up to 1,800 seconds, then repair each selected task and emit a durable UTF-8 log without exposing message content.

- [ ] **Step 6: Run CLI and full test suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 7: Commit CLI**

```powershell
git add compatibility_repair_cli.py tests/test_cli.py
git commit -m "feat: add interactive compatibility repair workflow"
```

### Task 3: Build, documentation, and isolated EXE smoke test

**Files:**
- Create: `build-exe.ps1`
- Create: `requirements-build.txt`
- Create: `tests/exe_fixture.py`
- Create: `.github/workflows/build.yml`
- Create: `README.md`
- Create: `LICENSE`
- Create: `.gitignore`

**Interfaces:**
- Consumes: `compatibility_repair_cli.py` as PyInstaller entry point.
- Produces: `dist/CodexSessionCompatibilityRepair.exe`.

- [ ] **Step 1: Add build and smoke-test fixture**

The fixture creates synthetic `%USERPROFILE%\.codex` data, invokes the EXE with scripted stdin, verifies repair output and unchanged non-target lines, and runs with a PATH that contains no Python executable.

- [ ] **Step 2: Add build script**

Use detected Python 3.11+, invoke `python -m PyInstaller --onefile --console --noupx`, and verify the target executable exists.

- [ ] **Step 3: Add public documentation and ignore rules**

Document supported record shape, backup modes, exact confirmations, restore procedure, limitations, and privacy guarantees. Ignore build output, caches, virtual environments, `*.jsonl`, `*.log`, backup directories, `.env`, and secret/config files.

- [ ] **Step 4: Run source tests locally and build EXE on GitHub Actions**

Run: `python -m unittest discover -s tests -v`

After publication, the Windows workflow installs the pinned build dependency, runs tests, builds the EXE, and uploads the artifact. Local software installation is not required.

- [ ] **Step 5: Run isolated EXE smoke test**

Run: `python tests\exe_fixture.py dist\CodexSessionCompatibilityRepair.exe`

Expected: PASS with fixture repaired and no Python dependency at runtime.

- [ ] **Step 6: Commit packaging and docs**

```powershell
git add .gitignore LICENSE README.md build-exe.ps1 requirements-build.txt tests/exe_fixture.py
git commit -m "build: package standalone Windows repair utility"
```

### Task 4: Final security review and GitHub publication

**Files:**
- Verify all tracked files.
- No new source files required.

**Interfaces:**
- Consumes: clean local `main` branch.
- Produces: public GitHub repository and pushed `main`.

- [ ] **Step 1: Run final verification**

Run full tests, rebuild the EXE, rerun isolated smoke test, and record executable SHA-256.

- [ ] **Step 2: Audit tracked content**

Run `git status --short`, `git diff --check`, `git ls-files`, and bounded secret-pattern scans. Confirm no `.jsonl`, `.log`, backup, `.env`, API key, token, or real session identifier is tracked.

- [ ] **Step 3: Inspect GitHub authentication and namespace**

Run `gh auth status` and confirm the authenticated account does not already have a conflicting repository.

- [ ] **Step 4: Create and push public repository**

Run `gh repo create codex-session-compatibility-repair --public --source . --remote origin --push`.

- [ ] **Step 5: Verify publication**

Confirm remote visibility is `PUBLIC`, default branch is `main`, local `HEAD` equals remote `main`, and repository contents match the audited tracked set.
