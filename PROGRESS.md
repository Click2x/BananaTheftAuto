# Progress log

An honest record of what has been tried on Banana Theft Auto's runtime side, what was measured, and what is still
unknown. Newest entries last. Everything here was run on one Windows 11 PC (Intel i7-12700K, NVIDIA RTX 3090, 64 GB RAM)
with the user's own copy of package 1.0.2.1. **The game does not play.** At the last entry it reaches a black window.

**What is not published here:** game files, bytes, disassembly or offsets into the game executable, shader outputs, and run
logs. Findings are given as slot numbers, call shapes, counts and results. Run logs stay on the machine that made them.

**How the facts were found:** by running the runtime and reading its own logs, by disassembling the user's copy of the
executable locally to understand a call, and by reading the public notes of other projects for the same game and layout
([xcl-dev/xcl](https://github.com/xcl-dev/xcl) GPL-2.0-only, [Marvisak/VIctory](https://github.com/Marvisak/VIctory),
[DesignWithTommy/Neonbridge](https://github.com/DesignWithTommy/Neonbridge)). **Only facts were taken from them (what a slot
is, what a signature looks like); none of their code was used.** Where a fact came from there, the entry says so.

**Upstream policy:** this is a standalone project. Nothing is pulled from the original Leonida repository automatically. It was
merged in once (upstream `main` at `66d4f5aa3`, 2026-11-24); further upstream changes are looked at by hand and only the
relevant ones are brought in.

## How to reproduce a run

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_logged.ps1 -Port <port folder> -Experiments -TitleWindow -TimeoutSec 140
```

`-Experiments` turns on every off-by-default switch listed below. `LEONIDA_STACKS=25,70,120` (set before the run) prints every
thread's stack at those seconds. Logs and a short `summary.txt` go to a new folder under `D:\Leonida-work\runlogs`.

## 2026-11-25 (first long session)

### Shader translation: 1,685 -> 2,615 of 2,684 library programs
- `llvm-mc` 21.1.8 reported 2 to 100 undecodable words in 999 of the pipeline library's compute programs, and the translator
  refuses such programs. 775 of them are variants of one shader (`CS_RaytracingResolve`).
- The project's own decoder (`tools/rdna2_decode.py`) decodes 966 of those 999 with no invalid words. `shader_library.py` now
  falls back to it (`--llvm-only` turns that off). On one run **2,615 of 2,684 translated and every one passed `spirv-val`**
  (was 1,685). 69 are still refused (lane-mask instructions, a few undecodable words, encodings the translator's cross-check
  rejects). Effect on the game: the title's "no translated compute shader" failures went from 6 to 0 in a 120 s run. Not checked:
  whether the extra shaders change what is drawn.
- A separate one-line fix to `tools/shader_disasm.py` (send `llvm-mc` 16 bytes per line, not one huge line) took one program from
  31.6 s and 125 MB of warnings to 0.09 s with the same listing. See `README_MENU.md`.

### Runtime: from crashing at 3 seconds to running steadily with a window
All of these are **off by default** and are diagnostic experiments, not fixes. Each says what it does, why, and where the fact came from.

| Switch | What it does | Basis |
|---|---|---|
| `LEONIDA_XS_SLOT61_STUB` | Device slot 61 is called as `(descriptor*, output*)`; answers with 16 zero bytes. | Call shape measured; XCL calls it `CreateSamplerX`. The zero words are not a real sampler. |
| `LEONIDA_XS_SLOT108_GRI` | Device slot 108 (C-ABI struct return) served like `GetResourceAllocationInfo`. | Shape measured; XCL names it `GetResourceAllocationInfo2`. Approximate. |
| `LEONIDA_XS_CMDSIG105` | Indirect-argument type 105 in `CreateCommandSignature` replaced by a plain dispatch. | Measured; XCL calls type 105 `DispatchX`. |
| `LEONIDA_XS_CMDSIG_MESH` | A mesh-dispatch signature replaced by a dispatch one so creation succeeds. | Wrong for mesh pipelines; only gets past a creation check. |
| `LEONIDA_XS_QUEUE35_EXEC` | Queue slot 35 served as `ExecuteCommandLists`. | Measured shape; XCL calls it `ExecuteCommandListsX`. |
| `LEONIDA_XS_QUEUE_NEWER` | Queue slots 16, 17, 18 served as the PC `Signal`, `Wait`, `GetTimestampFrequency`. | XCL's newer-layout note; fixed a stack overwrite we measured. |
| `LEONIDA_XS_PAGEPOOL` | Device slot 74 answered as `RegisterPagePoolX(address, pages, index out)`. | XCL's signature; arguments fit. Nothing is registered. |
| `LEONIDA_A8_ANYFLAGS` | Lets `A8_UNORM` textures be created with any flags. | Our own finding: the title makes one the layer refused. |
| `LEONIDA_XS_FENCE12_CELL` | Fence slot 12 returns the address of a completed-value cell. | Upstream's retail-boot notes. |
| `LEONIDA_XS_LIST139_RESET` | Command-list slot 139 served as `Reset(allocator, state)`. | XCL's newer-layout note; fixed every `Close` failing. |
| `LEONIDA_XS_WINDOW` | `1`: open a window and attach the Vulkan presenter. `title`: present into the title's own window. | Our own wiring; the test code already did this. |
| `LEONIDA_STACKS` | Print every thread's stack at the listed seconds. | Our own diagnostic. |

Measured effect, in order: 1,655 D3D12 calls and a crash at 3 seconds -> 12,000 calls -> 30,000 calls without a crash -> every
command list closing (`Close` failures 1,655 -> 0) -> `PresentX` answered (about 2,600 in 140 s, 0 failed) -> a window that goes
from white to black.

### Where it stands now
- The title runs steadily (more than 5 minutes without a crash), clears its back buffer about 11 times a second and presents it.
  **It records no pipelines, draws, dispatches or copies.** The window is black.
- About 35 of the title's threads are waiting. Two kinds of thread are busy: roughly ten inside NVIDIA's shader compiler
  (`nvgpucomp64.dll`, a full core each for the whole run) and one thread that spent about 94% of a core in the CLZERO emulation (cause found and reduced, see below).
- Refused calls that may matter and are not understood yet: device slot 57 (`DeserializePipelineStateX` per XCL) 10,241 times;
  the console texture-layout calls (`XGCreateTextureComputer`); queue slot 31 (looks like a page-pool call); allocator slot 9.

### Tests
- The runtime's own suite (`ctest`, 306 tests): 303 passed, 1 failed, 4 skipped for lack of a suitable GPU path. The one
  failure, `d3d12_close_parity` (the layer refuses 17 scissor rectangles, this Windows build's WARP accepts them), **fails the
  same way with `d3d12_com.cpp` and `d3d12_trace.h` at their upstream versions**, so it is not caused by this work. It looks
  like WARP behaviour on Windows build 26200 and has not been looked into further.
- `tests/test_shader_library.py` (23 tests) and `tests/test_shader_disasm.py` (31 tests) pass, `cpu_emulation_test` passes.

### Next steps
1. ~~CLZERO emulation CPU~~ done: see "CLZERO emulation" below.
2. Find what the roughly ten NVIDIA shader-compiler threads are compiling for minutes, and whether the title waits for it.
3. Find what the title's render thread waits on (thread-stack dumps with `LEONIDA_STACKS`), now that it presents.
4. Look at the refused calls listed above (slot 57 x 10,241, texture-layout calls, queue slot 31, allocator slot 9).
5. Keep this log and the README current; commit and push to this repo's `main` at each small milestone.

### CLZERO emulation: cause found and reduced
A 30-sample stack profile put 27 samples in `VirtualQuery` (the emulation's check that memory is writable), called once per
small block the title clears. The span last found writable is now remembered per thread and blocks inside it are written
directly, with the exact check as fallback if that write faults. Measured on one 62 s run: no sample in the emulation any more;
the title thread that did the clearing used 11.7 s of CPU over 50 s (about 23%, and that is now the title's own code, not ours),
down from about 94% of a core. Behavioural difference, noted in the code: a guard page appearing inside a remembered span is
consumed instead of delivered. `cpu_emulation_test` passes. The NVIDIA compiler threads are unchanged (about 41 s CPU each in 50 s).

### NVIDIA compiler threads: likely cause (not yet confirmed)
The log shows the title deserialising compute pipelines through device slot 67 (two calls failed with `E_INVALIDARG`; the log
only keeps the first few outcomes), and each success makes our layer build a Vulkan compute pipeline from a translated library
shader. That is the most likely source of about ten threads in `nvgpucomp64.dll` working for the whole run: the driver compiling
thousands of translated shaders. Not yet confirmed by counting successful slot-67 calls; next run should log a count.

### Things that were wrong along the way (kept for honesty)
- First guess for the failing `Close` calls: reopen lists when their allocator is reset. It reopened nothing; removed.
- First reading of the extra window: "not part of the run". It belongs to the game itself (the title's own window).
- The first CLZERO fix (one `VirtualQuery` per region, not per page) did not reduce that thread's CPU use; remembering the writable span did.
