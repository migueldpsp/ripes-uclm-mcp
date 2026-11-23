"""Headless runs through Ripes' own command line mode (``Ripes.exe --mode cli``).

The GUI does not expose assembler error messages through UI Automation, so we
use the CLI of the very same binary to check sources and to get exact,
machine-readable execution reports (registers, cycles, pipeline table).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

# Registers the GUI initialises by default (sp, gp). The CLI leaves them at 0,
# so we pass them explicitly to make headless runs match the window.
DEFAULT_REGINIT = "gpr:2=0x7ffffff0,3=0x10000000"

PROCESSORS = [
    "RV32_SS", "RV32_5MC_2M", "RV32_5MC_1M", "RV32_5S_NO_FW_HZ", "RV32_5S_NO_HZ",
    "RV32_5S_NO_FW", "RV32_5S", "RV32_5S_1S", "RV32_5S_1S_DB", "RV32_5S_2S_DB",
    "RV32_5S_3S", "RV32_5S_3S_DB", "RV32_6S_DUAL",
    "RV64_SS", "RV64_5MC", "RV64_5MC_1M", "RV64_5S_NO_FW_HZ", "RV64_5S_NO_HZ",
    "RV64_5S_NO_FW", "RV64_5S", "RV64_5S_1S", "RV64_5S_1S_DB", "RV64_5S_2S_DB",
    "RV64_5S_3S", "RV64_5S_3S_DB", "RV64_6S_DUAL",
]

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _running_ripes_exe() -> Path | None:
    """Path of the executable behind an open Ripes main window, if any."""
    import win32api
    import win32con
    import win32gui
    import win32process

    found: list[int] = []

    def visit(hwnd, _):
        if win32gui.GetWindowText(hwnd) == "Ripes" and win32gui.GetClassName(hwnd).startswith("Qt"):
            found.append(win32process.GetWindowThreadProcessId(hwnd)[1])

    win32gui.EnumWindows(visit, None)
    for pid in found:
        try:
            handle = win32api.OpenProcess(
                win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            try:
                exe = Path(win32process.GetModuleFileNameEx(handle, 0))
            finally:
                win32api.CloseHandle(handle)
        except Exception:
            continue
        if exe.is_file() and exe.name.lower() == "ripes.exe":
            return exe
    return None


def ripes_exe() -> Path:
    """Ripes.exe from RIPES_PATH, or else the one that is currently open."""
    path = os.environ.get("RIPES_PATH", "").strip()
    if path:
        exe = Path(path)
        if not exe.is_file():
            raise RuntimeError(f"RIPES_PATH does not point to an existing file: {exe}")
        return exe
    exe = _running_ripes_exe()
    if exe is None:
        raise RuntimeError("Ripes.exe not found: open Ripes, or set the RIPES_PATH "
                           "environment variable to the full path of Ripes.exe")
    return exe


def run_cli(source: str, processor: str = "RV32_SS", isa_extensions: str = "M",
            reginit: str | None = DEFAULT_REGINIT, timeout_ms: int = 5000,
            source_type: str = "asm") -> dict:
    """Assemble and run ``source`` headlessly and return the parsed report."""
    if processor not in PROCESSORS:
        raise ValueError(f"Unknown processor {processor!r}. Options: {', '.join(PROCESSORS)}")
    exe = ripes_exe()
    with tempfile.TemporaryDirectory(prefix="ripes_mcp_") as tmp:
        src = Path(tmp) / ("program.s" if source_type == "asm" else "program.c")
        src.write_text(source, encoding="utf-8")
        report = Path(tmp) / "report.json"
        args = [str(exe), "--mode", "cli", "--src", str(src), "-t", source_type,
                "--proc", processor, "--json", "--all", "--timeout", str(timeout_ms),
                "--output", str(report)]
        if isa_extensions:
            args += ["--isaexts", isa_extensions]
        if reginit:
            args += ["--reginit", reginit]
        proc = subprocess.run(args, capture_output=True, text=True, cwd=exe.parent,
                              timeout=timeout_ms / 1000 + 30, creationflags=NO_WINDOW)
        output = (proc.stdout + proc.stderr).strip()
        result: dict = {"ok": proc.returncode == 0, "exit_code": proc.returncode, "output": output}
        if report.is_file():
            try:
                result["report"] = json.loads(report.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                result["report_raw"] = report.read_text(encoding="utf-8")
        if proc.returncode != 0:
            result["errors"] = [line for line in output.splitlines()
                                if line.startswith(("ERROR", "INFO"))] or [output]
        return result


def check_assembly(source: str, isa_extensions: str = "M", xlen: int = 32) -> dict:
    """Assemble only (the run is cut short) and report assembler errors, if any."""
    processor = "RV32_SS" if xlen == 32 else "RV64_SS"
    res = run_cli(source, processor=processor, isa_extensions=isa_extensions, timeout_ms=1)
    assembled = "Error during assembly" not in res["output"]
    return {"assembled": assembled,
            "errors": res.get("errors", []) if not assembled else []}
