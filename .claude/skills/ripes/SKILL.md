---
name: ripes
description: Drive the user's live UCLM Ripes (RISC-V simulator) window through the ripes MCP tools - write and assemble RISC-V code, choose single-cycle/multicycle/pipelined processors and UCLM cache layouts, step, run to breakpoints and inspect registers, memory, pipeline stages and cache statistics. Use for any Ripes, RISC-V assembly lab or computer architecture exercise.
---

# Driving Ripes

The `ripes_*` MCP tools act on the user's own Ripes window; they watch every
change live, so work step by step and keep the window meaningful.

## Workflow

1. `ripes_status` (or `ripes_launch` if Ripes is closed).
2. Pick the hardware the exercise asks for with `ripes_select_processor`
   (`preset` such as `RV32_SS`, `RV32_5MC_1M`, `RV32_5MC_2M`, `RV32_5S`,
   `RV32_5S_NO_FW`, `RV32_5S_NO_HZ`, `RV32_5S_NO_FW_HZ`) and, when caches matter,
   `ripes_select_cache` + `ripes_configure_cache`.
3. `ripes_set_source` with the program. If `assembled` is false, fix the error
   it reports (first error only) and send again. `ripes_check_assembly` checks
   code without touching the window.
4. `ripes_reset`, then either `ripes_step` (N cycles) or set breakpoints and
   `ripes_run` (acts as "continue" from a breakpoint).
5. Inspect: `ripes_get_registers`, `ripes_get_instruction_memory` (stage of each
   instruction), `ripes_read_memory` (`.data` starts at `0x10000000`),
   `ripes_get_console`, `ripes_get_execution_info`, `ripes_get_cache_info`.
6. `ripes_screenshot` when the datapath picture helps (signal values,
   forwarding paths, hazards, stalls). Use `ripes_step_back` to rewind.

## Conventions

- Programs start at `main` in `.text`; exit with `li a7, 10` + `ecall`; print an
  integer with `li a7, 1` (value in `a0`) + `ecall`.
- `ripes_cli_run` gives an exact headless report (registers, cycles, CPI and the
  pipeline table) for comparing processors without disturbing the window.
- Reads switch tabs (Processor for registers/execution info, Memory, Cache);
  finish on the tab that best shows the result to the user.
- Processor/cache selections persist in Ripes' settings; restore what the user
  had when the task was only an experiment.
