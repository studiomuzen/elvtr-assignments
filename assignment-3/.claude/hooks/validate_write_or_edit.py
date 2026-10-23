#!/usr/bin/env python3
"""
PostToolUse validation bridge for Write + Edit.

Reads the Claude Code hook payload from stdin, extracts the file path the tool
just wrote, and runs:

  * JSON files under `ELVATR GAME 1/Assets/Data/`, `.claude/state/`, or
    `.claude/messages/` → `scripts/validate_data.py <file>`. Writes to
    `.claude/logs/validation.jsonl`. On failure, prints the error block to
    stderr and exits 2 so Claude feeds the error back to the originating
    agent.

  * `.cs` files under `ELVATR GAME 1/Assets/` → fast standalone syntax check
    via Unity's bundled Mono csc at
    `/Applications/Unity/Hub/Editor/<v>/Unity.app/Contents/Resources/Scripting/MonoBleedingEdge/bin/csc`.
    Picks up class-level errors (missing braces, bad method signatures, unknown
    tokens). Does NOT type-check against UnityEngine — a full-fidelity compile
    needs the live Editor, which the hook can't block on. Full compile is still
    enforced by sentry's per-task Play-mode test run; this hook is the fast
    guard that catches "obviously broken" before it even reaches Unity.

Hook payload shape (as of 2026-10):

  {
    "session_id": "...",
    "tool_name":  "Write" | "Edit",
    "tool_input": {
      "file_path": "/abs/path/to/file",
      ... other fields depending on the tool
    },
    "tool_response": { ... }
  }

Exit codes:
  0  — file is clean (or not in scope for this hook).
  2  — validation failed; stderr has the error block.

All runs (pass or fail) append one JSON line to `.claude/logs/validation.jsonl`:
  { ts, event, tool, file, result, errors: [...], fix: "<empty for failures,
    reserved for future auto-fix>" }
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = REPO / ".claude" / "logs"
LOG_PATH = LOGS_DIR / "validation.jsonl"
VALIDATE_DATA = REPO / "scripts" / "validate_data.py"
GEN_ARCHITECTURE = REPO / "scripts" / "gen_architecture.py"
UNITY_DOTNET = Path(
    "/Applications/Unity/Hub/Editor/6000.4.6f1/Unity.app/Contents/"
    "Resources/Scripting/NetCoreRuntime/dotnet"
)
UNITY_CSC_DLL = Path(
    "/Applications/Unity/Hub/Editor/6000.4.6f1/Unity.app/Contents/"
    "Resources/Scripting/DotNetSdkRoslyn/csc.dll"
)
VENV_PYTHON = REPO / ".venv" / "bin" / "python"

# Paths where JSON files are schema-validated. All resolved against REPO.
JSON_PREFIXES = (
    "ELVATR GAME 1/Assets/Data/",
    ".claude/state/",
    ".claude/messages/",
)

# Path prefix for C# files we compile-check.
CS_PREFIX = "ELVATR GAME 1/Assets/"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_record(
    *,
    event: str,
    tool: str,
    file_path: str,
    result: str,
    errors: list[str],
    fix: str = "",
) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": iso_now(),
        "ts_epoch": time.time(),
        "event": event,
        "tool": tool,
        "file": file_path,
        "result": result,
        "errors": errors,
        "fix": fix,
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def regenerates_architecture(rel: str) -> bool:
    """True if a change to this file should trigger docs/architecture.md regen."""
    if rel == "CLAUDE.md":
        return True
    if rel.startswith(".claude/agents/") and rel.endswith(".md"):
        return True
    if rel.startswith(".claude/tasks/") and rel.endswith(".json"):
        return True
    if rel == ".claude/state/project.json":
        return True
    return False


def regen_architecture_diagrams(rel: str) -> None:
    """Run gen_architecture.py and log the outcome. Never blocks the hook —
    diagram regen is best-effort."""
    py = str(VENV_PYTHON) if VENV_PYTHON.exists() else "python3"
    result = subprocess.run(
        [py, str(GEN_ARCHITECTURE)],
        capture_output=True,
        text=True,
    )
    ok = result.returncode == 0
    log_record(
        event="architecture_regen",
        tool="internal",
        file_path="docs/architecture.md",
        result="pass" if ok else "fail",
        errors=[] if ok else [((result.stderr or result.stdout) or "")[:500]],
        fix=f"triggered by edit of {rel}",
    )


def repo_relative(abs_path: str) -> str | None:
    """Return the path relative to the repo root if it's inside it, else None."""
    try:
        p = Path(abs_path).resolve()
        return str(p.relative_to(REPO))
    except (ValueError, OSError):
        return None


def is_json_in_scope(rel: str) -> bool:
    if not rel.endswith(".json"):
        return False
    return any(rel.startswith(pref) for pref in JSON_PREFIXES)


def is_cs_in_scope(rel: str) -> bool:
    return rel.endswith(".cs") and rel.startswith(CS_PREFIX)


def validate_json(abs_path: str, tool: str) -> int:
    """Run scripts/validate_data.py on this one file."""
    py = str(VENV_PYTHON) if VENV_PYTHON.exists() else "python3"
    result = subprocess.run(
        [py, str(VALIDATE_DATA), abs_path],
        capture_output=True,
        text=True,
    )
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    rel = repo_relative(abs_path) or abs_path
    # Collect FAIL lines from stdout
    errors = [ln for ln in stdout.splitlines() if ln.startswith("FAIL")]
    if result.returncode != 0 and not errors:
        # Something went wrong (import error / IO error). Record stderr.
        errors = ["validator exit != 0: " + (stderr or stdout)[:500]]

    if errors:
        log_record(event="json_validate", tool=tool, file_path=rel,
                   result="fail", errors=errors)
        sys.stderr.write(
            "VALIDATION FAILED — JSON schema check on " + rel + "\n\n"
            + stdout + "\n"
            + ("\n" + stderr if stderr else "")
            + "\n\nFix the schema violations above and re-save. "
              "The hook will re-run on the next Write/Edit.\n"
        )
        return 2

    log_record(event="json_validate", tool=tool, file_path=rel,
               result="pass", errors=[])
    return 0


def syntax_check_cs(abs_path: str, tool: str) -> int:
    """Fast standalone C# syntax check via Unity's bundled Mono csc.

    We invoke the compiler with `-target:library` + the single source file +
    `-nowarn:0168,0219,0414` to suppress harmless warnings. We tolerate
    "type / namespace not found" style errors (CS0246, CS0234, CS0103) because
    the file is being compiled in isolation without UnityEngine / Ambush
    references — those type errors are false positives at this tier. Real
    errors we DO catch: unbalanced braces, bad method signatures, syntax
    typos, invalid tokens.
    """
    rel = repo_relative(abs_path) or abs_path

    if not UNITY_DOTNET.exists() or not UNITY_CSC_DLL.exists():
        # Hook can't block without a compiler available; log + no-op pass.
        log_record(event="cs_syntax_check", tool=tool, file_path=rel,
                   result="skipped",
                   errors=[f"Unity dotnet/csc not found at {UNITY_DOTNET} / {UNITY_CSC_DLL}"])
        return 0

    out_dll = f"/tmp/hook_cs_{os.getpid()}.dll"
    result = subprocess.run(
        [str(UNITY_DOTNET), str(UNITY_CSC_DLL),
         "-target:library",
         "-nowarn:0168,0219,0414",
         f"-out:{out_dll}",
         abs_path],
        capture_output=True,
        text=True,
    )
    try:
        os.remove(out_dll)
    except OSError:
        pass

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    output = stdout + ("\n" + stderr if stderr else "")

    # Classify errors. Tolerate missing-reference errors (CS0246 / CS0234 /
    # CS0103 for UnityEngine / Ambush symbols) because we deliberately did not
    # pass -r:UnityEngine.dll. Those codes catch real errors elsewhere in a
    # file that happens to lack a reference, but the live Editor compile is
    # where that gets enforced; this hook only guards obvious syntax breakage.
    # Tolerated because we deliberately compile this file in isolation (no -r:
    # UnityEngine.dll, no -r:Ambush.*, no mscorlib). Any symbol-resolution or
    # predefined-type error falls out of a cross-reference check that only the
    # live Unity Editor can do; sentry runs the real compile per-task via the
    # Play-mode test harness.
    tolerated_codes = {
        "CS0246",  # type or namespace not found
        "CS0234",  # type/ns does not exist in namespace X
        "CS0103",  # name 'X' does not exist in the current context
        "CS1061",  # 'T' does not contain a definition for 'X'
        "CS0117",  # 'T' does not contain a definition for 'X' (static)
        "CS0122",  # 'X' is inaccessible due to its protection level
        "CS0116",  # namespace cannot directly contain members
        "CS0518",  # predefined type 'System.*' is not defined or imported
        "CS0012",  # type is defined in assembly that is not referenced
        "CS0535",  # does not implement interface member
        "CS1069",  # type-name could not be found in a namespace
    }
    real_errors: list[str] = []
    for ln in output.splitlines():
        if "): error CS" not in ln and "): warning CS" not in ln:
            continue
        if "): warning " in ln:
            continue
        # Parse CS code
        try:
            code = ln.split("error ")[1].split(":")[0].strip()
        except Exception:
            code = "CS?"
        if code in tolerated_codes:
            continue
        real_errors.append(ln.strip())

    if real_errors:
        log_record(event="cs_syntax_check", tool=tool, file_path=rel,
                   result="fail", errors=real_errors)
        sys.stderr.write(
            "VALIDATION FAILED — C# syntax check on " + rel + "\n\n"
            + "\n".join(real_errors) + "\n\n"
            + "Fix the syntax errors above and re-save. "
              "The hook will re-run on the next Write/Edit. (Note: this "
              "hook tolerates missing-reference errors — type-level checks "
              "run via sentry's full Play-mode test pass.)\n"
        )
        return 2

    log_record(event="cs_syntax_check", tool=tool, file_path=rel,
               result="pass", errors=[])
    return 0


def main() -> int:
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0

    tool_name = payload.get("tool_name") or payload.get("tool") or ""
    if tool_name not in ("Write", "Edit"):
        return 0

    tool_input = payload.get("tool_input") or payload.get("parameters") or {}
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not file_path or not os.path.isabs(file_path):
        return 0

    rel = repo_relative(file_path)
    if not rel:
        return 0

    exit_code = 0
    if is_json_in_scope(rel):
        exit_code = validate_json(file_path, tool_name)
    elif is_cs_in_scope(rel):
        exit_code = syntax_check_cs(file_path, tool_name)

    # Regen the architecture docs after any edit that touches the generator's
    # inputs. Best-effort — the regen itself never blocks the hook.
    if regenerates_architecture(rel):
        regen_architecture_diagrams(rel)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
