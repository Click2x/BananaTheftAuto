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
- A later full run with `ctest -j8` also failed `device_proxy_trace`; run alone it passes (0.05 s), so it looks sensitive to parallel runs. Not investigated further.
- `tests/test_shader_library.py` (23 tests) and `tests/test_shader_disasm.py` (31 tests) pass, `cpu_emulation_test` passes.

### Next steps
1. Find the producer that fills the six pointer/size pairs and what the pairs are (state blocks and shader code per stage).
2. Find what waits on the completion counter, to confirm the hypothesis above.
3. Scope a minimal graphics-pipeline path (the project's docs cover compute pipelines only); a first test is to answer slot 57
   with a stub pipeline object and see whether the title then proceeds to record draws.
4. Other refused calls (texture-layout calls, queue slot 31, allocator slot 9).
5. Keep this log and the README current; commit and push at each small milestone.

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
thousands of translated shaders. Measured on a 100 s run: slot 67 is called only about 304 times in total (calls 302 and 304 failed with `E_INVALIDARG`, the rest succeeded) and then stops. So the driver compiles about 300 pipelines for minutes while the title makes no further pipeline calls: consistent with the title waiting for them, but the wait itself is not yet shown.

### What the title's threads wait on (90 s run, dumps at 40 s and 80 s)
Across both dumps, 38 of the non-NVIDIA thread samples sit in one kernel wait, 18 in another, and about 38 in an
infinite-timeout wait on an object made from a small helper in the title (it waits on one handle a given number of times).
**Correction to an earlier reading of these dumps:** I first took the busiest title thread to be in a poll-and-sleep loop. The
frame is a `WaitForSingleObject`-style call with an infinite timeout, i.e. an idle worker. The thread's CPU figure is
cumulative (it did about 11.7 s of work earlier in the run and then waits), so it says nothing about polling. What the workers
wait for (work that is never submitted, or a signal our layer should raise) is not identified yet.

### Device slot 57: shape measured (graphics pipelines?)
Slot 57 is called as `(description*, riid, out**)` 10,241 times and the layer forwards it to the PC slot of the same number,
which does not implement it (`E_NOTIMPL`), so every call fails. The description is a root-signature pointer followed by **six
pointer/size pairs** (sizes of 0x184, 0xbc, 0x1c0, 0xd0, 0x180 and 0x2f0 bytes in the one call dumped), the same pointer/size
pattern as slot 67's four pairs for compute. That fits XCL's name for it (pipeline-state deserialisation) and would make it the
graphics counterpart. If so, **the title cannot create any graphics pipeline, which would explain why it never records a
draw.** Not yet proven: the pair contents are not decoded, and this does not say how the graphics shaders would be
translated (the pipeline library's graphics programs are not translated by this project yet). The layer dumps these words
to the local log on the first failure. The four pairs whose parts could be read start with binary words, not the `FSPX`
magic, so they are raw state blocks; two of the six pointers point into different, much higher allocations (those are
probably the shader code, which the title keeps outside the payload). Graphics pipelines therefore do not arrive in the
FSPX form that slot 67 uses.
The part sizes of the first 24 calls (logged locally) show structure: part 1 is always 0x184 or 0x17c bytes, part 2 varies
(0x50 to 0xbc), and parts 3-4 and parts 5-6 each look like a pair that varies together (for example 0x1c0/0xd0, 0x140/0x90), the
way slot 67's kind 6 (program) and kind 7 (records) do. Some calls have parts 3 and 4 empty (size 0) and only the last pair, which
suggests the pairs are shader stages (a pipeline with one stage and one with two). That reading is a guess from sizes alone.

### Slot 57: who calls it and what happens on failure (read from the local disassembly)
The only caller is one task function that walks a linked list of queued pipeline requests. Each request record holds the
description inline: the root-signature pointer is written by the task just before the call, and the pointer/size pairs were
already filled by whoever queued the request (not yet found). The call passes the shared device, that description, a fixed
interface id and a local output slot. **On a failed result the task skips the record and moves to the next; on success it
publishes the pipeline, bumps a shared completion counter with a state mask, and signals.** So the title does not abort when
slot 57 fails, but it never gets the completions it counts, which fits the idle workers and a title that never starts drawing.
This is the strongest explanation so far and is still a hypothesis: nothing has yet been seen waiting on that counter.
The layer logs the first six frames of the caller on the first failure.

### Things that were wrong along the way (kept for honesty)
- First guess for the failing `Close` calls: reopen lists when their allocator is reset. It reopened nothing; removed.
- First reading of the extra window: "not part of the run". It belongs to the game itself (the title's own window).
- A first reading of thread-stack dumps as a polling loop: the frame was an infinite wait and the CPU figure cumulative.
- The first CLZERO fix (one `VirtualQuery` per region, not per page) did not reduce that thread's CPU use; remembering the writable span did.
