"""MCP server exposing a live, unmodified UCLM Ripes window as tools.

Every UI Automation call runs on one dedicated thread that owns the COM
apartment (pywinauto is imported there), so tool calls never race each other.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
from typing import Any, Callable

try:  # mcp >= 2
    from mcp.server.mcpserver import Image, MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server, Image
    from mcp.server.fastmcp.exceptions import ToolError

from . import cli_runner


def _init_ui_thread() -> None:
    import pythoncom

    pythoncom.CoInitialize()
    import pywinauto  # noqa: F401  (creates its UIA COM objects on this thread)


_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="ripes-ui", initializer=_init_ui_thread)
_controller = None


def _ctl():
    global _controller
    if _controller is None:
        from .controller import RipesController

        _controller = RipesController()
    return _controller


async def _ui(fn: Callable[..., Any], *args, **kwargs) -> Any:
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(_executor, functools.partial(fn, *args, **kwargs))
    except ToolError:
        raise
    except Exception as exc:  # surface the reason to the assistant, not a generic error
        raise ToolError(str(exc) or type(exc).__name__) from exc


async def _thread(fn: Callable[..., Any], *args) -> Any:
    try:
        return await asyncio.to_thread(fn, *args)
    except Exception as exc:
        raise ToolError(str(exc) or type(exc).__name__) from exc


def _call(method: str):
    """Run ``RipesController.<method>`` on the UI thread."""
    async def runner(*args, **kwargs):
        return await _ui(lambda: getattr(_ctl(), method)(*args, **kwargs))
    return runner


def _parse_address(address: str | int) -> int:
    return address if isinstance(address, int) else int(str(address), 0)


mcp = _Server(
    "ripes-uclm",
    instructions=(
        "Controls the user's own Ripes window (UCLM fork v1.1, a RISC-V simulator) live: "
        "every action is visible on screen. Typical loop: ripes_set_source -> ripes_reset -> "
        "ripes_step / ripes_run -> ripes_get_registers / ripes_read_memory / "
        "ripes_get_instruction_memory. Use ripes_screenshot to see the datapath. "
        "Some reads switch the visible tab (registers/execution info live in the Processor tab, "
        "memory in the Memory tab). ripes_cli_run runs a program headlessly without touching the "
        "window. Processor and cache choices are saved by Ripes in its settings."
    ),
)


# ---------------------------------------------------------------- window / state

@mcp.tool()
async def ripes_launch() -> dict:
    """Start Ripes if it is not already running (needs the RIPES_PATH environment variable)."""
    return await _call("launch")()


@mcp.tool()
async def ripes_status() -> dict:
    """Processor model, visible tab, and whether the simulation is running/finished."""
    return await _call("status")()


@mcp.tool()
async def ripes_screenshot() -> Image:
    """PNG screenshot of the Ripes window (datapath, panels, values) to look at."""
    data = await _call("screenshot")()
    return Image(data=data, format="png")


@mcp.tool()
async def ripes_show_tab(tab: str) -> str:
    """Show a tab: 'editor', 'processor', 'cache', 'memory' or 'io'."""
    return await _call("show_tab")(tab)


# ------------------------------------------------------------------------ editor

@mcp.tool()
async def ripes_set_source(code: str) -> dict:
    """Replace the assembly code in the Ripes editor. Ripes assembles it at once.

    Returns whether it assembled, the assembler errors (checked with the Ripes
    CLI, which reports the first error) and the disassembled program.
    """
    return await _call("set_source")(code)


@mcp.tool()
async def ripes_get_source() -> str:
    """Current contents of the Ripes code editor."""
    return await _call("get_source")()


@mcp.tool()
async def ripes_get_program() -> str:
    """Assembled program as shown in 'Executable code' (disassembled or binary view)."""
    return await _call("get_program")()


@mcp.tool()
async def ripes_set_view_mode(mode: str) -> str:
    """Executable code view: 'disassembled' or 'binary'."""
    await _call("set_view_mode")(mode)
    return mode


@mcp.tool()
async def ripes_load_file(path: str) -> dict:
    """Load an assembly file (.s) from disk into the Ripes editor."""
    return await _call("load_file")(path)


@mcp.tool()
async def ripes_save_source(path: str) -> str:
    """Save the editor contents to a file on disk; returns the absolute path."""
    return await _call("save_source")(path)


# -------------------------------------------------------------------- simulation

@mcp.tool()
async def ripes_reset() -> dict:
    """Reset the processor (F3): PC, registers and memory go back to the start."""
    return await _call("reset")()


@mcp.tool()
async def ripes_step(cycles: int = 1) -> dict:
    """Advance the processor by N clock cycles (Clock, F5)."""
    return await _call("clock")(max(1, cycles))


@mcp.tool()
async def ripes_step_back(cycles: int = 1) -> dict:
    """Undo N clock cycles (Reverse, F4)."""
    return await _call("reverse")(max(1, cycles))


@mcp.tool()
async def ripes_run(timeout_seconds: float = 10.0) -> dict:
    """Run (F8) until the program exits or reaches a breakpoint. Works as 'continue'
    when already stopped on a breakpoint. Stops itself after timeout_seconds."""
    return await _call("run")(timeout_seconds)


@mcp.tool()
async def ripes_auto_clock(enable: bool, interval_ms: int | None = None) -> dict:
    """Start/stop auto clocking (F6) so the user can watch execution; optional interval."""
    return await _call("auto_clock")(enable, interval_ms)


@mcp.tool()
async def ripes_get_execution_info() -> dict:
    """Cycles, instructions retired, CPI, IPC and clock rate (Processor tab)."""
    return await _call("execution_info")()


# ------------------------------------------------------------------ inspection

@mcp.tool()
async def ripes_get_registers() -> dict:
    """All general purpose registers (name, ABI alias, displayed value, unsigned value)."""
    return await _call("registers")()


@mcp.tool()
async def ripes_get_instruction_memory(include_breakpoints: bool = False) -> list:
    """Instruction memory panel: address, instruction and the pipeline stage each
    instruction is in now (IF/ID/EX/MEM/WB, or a dot for the single-cycle PC).
    include_breakpoints reads the BP column too (slower: scrolls the list)."""
    return await _call("instruction_memory")(include_breakpoints)


@mcp.tool()
async def ripes_get_console() -> str:
    """Text printed to the Ripes console (ecall output, exit messages)."""
    return await _call("console")()


@mcp.tool()
async def ripes_clear_console() -> str:
    """Clear the Ripes console."""
    await _call("clear_console")()
    return "cleared"


@mcp.tool()
async def ripes_read_memory(address: str, words: int = 8) -> list:
    """Read 32-bit words from data memory, e.g. address='0x10000000' (.data start)."""
    return await _call("read_memory")(_parse_address(address), max(1, min(words, 256)))


@mcp.tool()
async def ripes_get_memory_map() -> list:
    """Memory sections (.text, .data, .bss, I/O devices) with sizes and ranges."""
    return await _call("memory_map")()


# ----------------------------------------------------------------- breakpoints

@mcp.tool()
async def ripes_set_breakpoint(address: str, enabled: bool = True) -> dict:
    """Set or clear the breakpoint of the instruction at address (e.g. '0x14')."""
    return await _call("set_breakpoint")(_parse_address(address), enabled)


@mcp.tool()
async def ripes_list_breakpoints() -> list:
    """Addresses that currently have a breakpoint."""
    return await _call("breakpoints")()


@mcp.tool()
async def ripes_clear_breakpoints() -> list:
    """Remove every breakpoint; returns the addresses that were cleared."""
    return await _call("clear_breakpoints")()


# --------------------------------------------------------------- configuration

@mcp.tool()
async def ripes_select_processor(
    preset: str | None = None,
    datapath: str | None = None,
    xlen: int | None = None,
    branch_strategy: str | None = None,
    branch_slots: int | None = None,
    forwarding: bool | None = None,
    hazard_detection: bool | None = None,
    extensions: dict[str, bool] | None = None,
    layout: str | None = None,
) -> dict:
    """Choose the processor through Ripes' 'Select processor' dialog.

    preset: a Ripes CLI name such as RV32_SS, RV32_5MC_1M, RV32_5MC_2M,
    RV32_5S, RV32_5S_NO_FW, RV32_5S_NO_HZ, RV32_5S_NO_FW_HZ, RV32_5S_1S,
    RV32_5S_1S_DB, RV32_6S_DUAL (or RV64_*). Explicit fields override it:
    datapath ('single', 'multicycle_1m', 'multicycle_2m', 'pipelined',
    'dual_issue'), branch_strategy ('predict_not_taken', 'delayed_branch'),
    branch_slots (1-3), forwarding, hazard_detection, extensions ({'M': true,
    'C': false}), layout ('Standard', 'Extended', ...).
    """
    return await _call("select_processor")(
        preset=preset, xlen=xlen, datapath=datapath, branch_strategy=branch_strategy,
        branch_slots=branch_slots, forwarding=forwarding, hazard_detection=hazard_detection,
        extensions=extensions, layout=layout)


@mcp.tool()
async def ripes_select_cache(cache_type: str) -> dict:
    """UCLM cache organisation: 'l1_split', 'l1_unified' or 'multilevel'."""
    return await _call("select_cache")(cache_type)


@mcp.tool()
async def ripes_get_cache_info() -> list:
    """Configuration and statistics (hits, misses, hit rate, writebacks) of each cache."""
    return await _call("cache_info")()


@mcp.tool()
async def ripes_configure_cache(
    level: str | None = None,
    preset: str | None = None,
    ways: int | None = None,
    sets_log2: int | None = None,
    words_per_line_log2: int | None = None,
    replacement_policy: str | None = None,
    write_hit: str | None = None,
    write_miss: str | None = None,
) -> dict:
    """Configure one cache of the Cache tab (level = tab name, e.g. 'L1 Data').

    ways is the number of ways; sets_log2 and words_per_line_log2 are the 2^N
    spin boxes. replacement_policy: 'LRU', 'Random', ...; write_hit:
    'Write-back' / 'Write-through'; write_miss: 'Write allocate' / 'No write allocate'.
    """
    return await _call("configure_cache")(
        level=level, preset=preset, ways=ways, sets_log2=sets_log2,
        words_per_line_log2=words_per_line_log2, replacement_policy=replacement_policy,
        write_hit=write_hit, write_miss=write_miss)


# --------------------------------------------------------------------- headless

@mcp.tool()
async def ripes_cli_run(
    code: str,
    processor: str = "RV32_SS",
    isa_extensions: str = "M",
    timeout_ms: int = 5000,
) -> dict:
    """Run assembly headlessly with the Ripes CLI (does not touch the window).

    Returns exit status, console output and a report with registers, cycles,
    CPI/IPC and the full pipeline diagram. sp/gp start as in the GUI.
    """
    return await _thread(cli_runner.run_cli, code, processor, isa_extensions,
                                   cli_runner.DEFAULT_REGINIT, timeout_ms)


@mcp.tool()
async def ripes_check_assembly(code: str, isa_extensions: str = "M") -> dict:
    """Assemble without touching the window and report the first assembler error."""
    return await _thread(cli_runner.check_assembly, code, isa_extensions)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
