"""Local Python execution tool for the analytics agent.

Anthropic ran analysis code in a remote ``code_execution`` sandbox and accepted a
``container_upload`` file. DeepSeek offers neither, so the analytics agent keeps
its "write pandas, read the output" workflow by executing the model's code here
instead — in a subprocess, in a throwaway working directory that contains only
the data file being analyzed.

SECURITY: this runs model-generated code on the API server with the server's own
privileges. It is bounded by a wall-clock timeout, an output cap, and an isolated
working directory, but it is **not** a sandbox — there is no filesystem or network
confinement. Set ``MARKETING_AGENT_LOCAL_CODE_EXEC=0`` to turn the tool off; the
analytics agent then reports that analysis is unavailable rather than executing
anything. For a hardened deployment, run the API server itself inside a container
with no outbound network and a read-only root filesystem.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_FALSEY = {"0", "false", "no", "off", ""}

TIMEOUT_SECONDS = int(os.environ.get("MARKETING_AGENT_CODE_EXEC_TIMEOUT", "120"))
MAX_OUTPUT_CHARS = 20_000

RUN_PYTHON_TOOL = {
    "name": "run_python",
    "description": (
        "Execute Python 3 code and return everything it prints. pandas, numpy and "
        "openpyxl are available. The working directory contains the data file for this "
        "task; read it by its filename. State is NOT preserved between calls, so each "
        "call must be a complete, self-contained script. Print only computed results — "
        "never dump entire dataframes."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "A complete Python script. Use print() for anything you need to read back.",
            }
        },
        "required": ["code"],
    },
}


def enabled() -> bool:
    """Local code execution enabled? Default on; set MARKETING_AGENT_LOCAL_CODE_EXEC=0 to disable."""
    return os.environ.get("MARKETING_AGENT_LOCAL_CODE_EXEC", "1").strip().lower() not in _FALSEY


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... [output truncated at {MAX_OUTPUT_CHARS} characters]"


def run_python(code: str, data_file: Path | None = None) -> str:
    """Run ``code`` in a scratch directory holding ``data_file``; return its output."""
    if not enabled():
        return "Error: local code execution is disabled on this server (MARKETING_AGENT_LOCAL_CODE_EXEC=0)."
    code = (code or "").strip()
    if not code:
        return "Error: run_python requires non-empty 'code'."

    workdir = Path(tempfile.mkdtemp(prefix="marketing_agent_exec_"))
    try:
        if data_file is not None and data_file.exists():
            shutil.copy2(data_file, workdir / data_file.name)
        script = workdir / "_analysis.py"
        script.write_text(code, encoding="utf-8")

        env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "MPLBACKEND": "Agg",
        }
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(script)],
                cwd=workdir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_SECONDS,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return f"Error: the script exceeded the {TIMEOUT_SECONDS}s execution limit and was killed."

        parts: list[str] = []
        if proc.stdout.strip():
            parts.append(proc.stdout.strip())
        if proc.returncode != 0:
            parts.append(f"[exit code {proc.returncode}]")
            if proc.stderr.strip():
                parts.append(proc.stderr.strip()[-4000:])
        elif proc.stderr.strip():
            parts.append(f"[stderr]\n{proc.stderr.strip()[-2000:]}")
        if not parts:
            return "The script ran successfully but printed nothing. Add print() calls for the results you need."
        return _truncate("\n\n".join(parts))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def make_handler(data_file: Path | None):
    """Build a ``run_python`` handler bound to one data file, for ``run_agent``."""

    def handle(payload: dict) -> str:
        return run_python(str(payload.get("code") or ""), data_file)

    return handle
