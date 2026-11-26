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
1. Look at what is on screen (frame capture) and what the first submitted frames contain; compare with the draw counts.
2. Add a build stage for the graphics library (the by-hand commands are in the graphics translation section), so a fresh
   build produces `fspx_gfx` without manual steps.
3. The 235 graphics programs that did not translate (`v_interp_p2_f16` words, 6 without a container) and the 69 compute ones.
4. Other refused calls (texture-layout calls, queue slot 31, allocator slot 9); re-check which of them still occur on the merged build.
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

### How upstream handles slot 57 (looked at read-only through the GitHub web API on 2026-11-25; nothing fetched or merged)
Upstream (535 commits ahead of the one merge on 2026-11-24) already treats slot 57 as the graphics pipeline deserialiser
and answers it with a **native graphics factory** (`d3d12_xs_native_pso.h`, with `_fallback.h`, plus a PSO-stream reader). Its
documented layout of the description is the same one measured here: root signature, then a state blob (about 380-404 bytes), a
pipeline blob (80-224 bytes; holds the vertex input layout), and two program/stage pairs (pixel and vertex shaders).
Programs are looked up in a library of translated graphics programs by hash, and the state blob's colour-target, blend, depth,
stencil and raster registers are decoded into PC pipeline state. So the open question above (are the pairs shader stages?)
has an answer: yes. Our hypothesis that failing slot 57 starves the title of draws is consistent with their progress, since their
boot graphs show draws once it is served. **Not brought in:** by the project's rule, upstream changes are chosen by hand; a list
of candidates has been given to the user for a decision. (The layout facts here match, but this log only claims what was measured
locally.)

### Porting upstream's slot 57 path (on the local branch `port-slot57`; not on `main` yet)
The native graphics-pipeline path is not separable from the rest of upstream (the device proxy, the Vulkan device and the shader
library all changed around it), so it was brought in as a full merge of upstream `main` (71a769d7d) on a scratch branch, at the
user's request. Eight files conflicted. Resolution: upstream's versions of `d3d12_com.cpp`, `d3d12_vulkan_device.cpp`,
`startup_trace.h` (our `LEONIDA_STACKS` dumper re-applied on it), `shader_disasm.py` and its test, and `d3d12_xs_device.cpp`;
ours kept in `shader_library.py` (the Python-decoder fallback, now passing `wave32` through) and `d3d12_xs.cpp` (the
`LEONIDA_XS_WINDOW` presenter). **That drops our env-gated device experiments** (slot 61/108/105/queue/page-pool/fence/list-139
switches) because upstream's proxy replaces the file; upstream's `d3d12_com.cpp` replaces our Close diagnostics and its A8
handling replaces `LEONIDA_A8_ANYFLAGS`. They were not re-tested one by one.
Measured on a 100 s run with the merged build (needs the new `gta6rt_tls_host.dll` beside the exe):

| | before (ours) | merged |
|---|---|---|
| D3D12 calls traced | about 60,000 | 118,899 |
| `DrawInstanced` recorded | 0 | 2,128 |
| `SetPipelineState` | 0 | 2,128 |
| `PresentX` ok | about 2,600 per 140 s | 1,064 |
| native graphics pipelines (slot 57) | 0 of 10,241 refused | 1,258 created, 11,994 failed |

No crash in the window. The 11,994 failures are because the translated graphics-program library (`fspx_gfx`) is empty here: no
tool in the tree generates it (`docs/shader_library.md`: "Graphics pipelines are not translated by the build", and upstream's own
boot sample also shows `0 fspx_gfx`). So draws are recorded but the pipelines that need a translated vertex or pixel shader
cannot be built. The run's log also reports `no translated vs` for the game's own shaders. Tests on the merged branch: `ctest`
420 of 420 pass (including `d3d12_close_parity`, which failed before), `test_shader_library.py` 24 and `test_shader_disasm.py` 31 pass.

### Graphics shader translation: what it needs, and the first full run (2026-11-25)
No build stage translates the pipeline library's graphics programs, but the tools for it exist and work when run by hand
(nothing here is game data; outputs stay in the work folder):

```powershell
# SPIRV-Tools (spirv-as, spirv-val) on PATH and LLVM_MC pointing at llvm-mc
python -I tools\shader_library.py <package>\shaders.rpf --out <work>\gfxlib --stages vs,ps --disasm --carve <work>\shaders\dxbc --jobs 10
python -I tools\rdna2spirv.py <work>\gfxlib\disasm --out <work>\gfxspirv
# then put the result at <work>\shaders\spirv\fspx_gfx (its index.json carries stage and fspx_code_sha256 per program)
```

`--carve` matters: the translator reads each program's input/output signatures from its source shader container, and without
it every program is refused ("no shader container"). Results: 11,339 vertex and pixel programs extracted (the Python decoder
fallback decoded 2,096 that llvm-mc could not); **11,104 translated and all 11,104 pass `spirv-val`**; 235 did not
(mostly `v_interp_p2_f16` words llvm-mc prints with a field dropped, and 6 without a container). Of the 11,104, 7,202 are
wave-64 graphics shaders marked tier C, which the translator itself says are not exact on 32-wide GPUs such as this
RTX 3090 (see `wave64_graphics_reasons` in the index). The full translation took about 50 minutes.

With them installed (120 s run, merged build): D3D12 calls 188,438 (118,899 before); `DrawIndexedInstanced` 8,022 and
`DrawInstanced` 3,128 recorded; `Dispatch` 501; `SetPipelineState` 4,079; `PresentX` 1,564; no crash. **Native graphics
pipelines still fail 12,062 of 13,388 times.** The log gives the main reason: the game's own mesh shaders (translated by an
earlier build) "were translated before the graphics root window; translate the shaders again (`make_game.py --stages
shaders`)", thousands of times. So the old translated game shaders need retranslating with the current translator. Not
checked yet: whether the window shows anything (it was not looked at in this run).

### After retranslating the game's own shaders (2026-11-25, 120 s run)
`make_game.py --stages shaders` (about 41 minutes, 10 processes, wave64 emulation on because this GPU is 32 wide) redid the
translation of the game's own shaders with the current translator; `fspx_gfx` was moved aside during it and put back. The
runtime then loaded 40,376 translated shaders (2,705 fspx, 11,104 fspx_gfx, 52 bvh, 12 exe).

| | merged, old shaders | merged, retranslated |
|---|---|---|
| native graphics pipelines (slot 57) created / failed | 1,326 / 12,062 | **25,450 / 0** |
| `CreatePipelineState` failed | 15,012 | **4** |
| `DrawIndexedInstanced` + `DrawInstanced` | 11,150 | **18,381** |
| `Dispatch` | 501 | 810 |
| `SetPipelineState` | 4,079 | 6,299 |
| D3D12 calls traced | 188,438 | 223,060 |

No crash. **Every native graphics pipeline the title asked for was created.** The window's contents were looked at afterwards (see below: black); the title records no copies in this window, and its
submission log (`[rt] submit phases`) shows work per frame that has not been analysed yet. Wave-64 tier C programs (7,202 of
the graphics ones) are not exact on this GPU by the translator's own account, so wrong colours or missing effects are
expected when pictures do appear.

### What is on screen (looked at, 2026-11-25 afternoon)
**Black.** Two ways of looking, both agree:
- The title creates its window (`sgaWindowClass`, caption "Americas") **minimised** (it sits at -32000,-32000), so nothing is seen
  until it is restored; restored by hand it shows a black client area.
- `LEONIDA_CAPTURE=<dir> LEONIDA_CAPTURE_SOURCE=1` reads back the image each `PresentX` is given. The title alternates between two
  3840x2160 images (format 37, RGBA8) and **every texel of both is zero** (not even alpha) in all captured frames, in a 90 s run.
  So the presenter works; what it is handed was never drawn into (or is drawn and then cleared to zero).
- Same run: 1,191 `PresentX` calls (all ok), 939 `ClearRenderTargetView`, about 3,400 draws, 1,874 list submissions. The
  Khronos validation layer (`LEONIDA_VK_VALIDATION=1`) printed nothing on this path, which may only mean it is not used here.
- Correction/extension: while the window stays minimised the presenter cannot advance (the capture only ever reaches its first frame, even
  after 9 minutes and 9,773 `PresentX` calls). With the window restored the presenter does advance: 541 presented frames in 100 s
  were captured (both the window image and the source image), and **all of them are zero**. So black is real, not a minimised-window artefact.
- Where the draws go (new local diagnostic `LEONIDA_DRAW_STATS=1`, prints the first colour target of each replayed draw every 2,048 draws):
  in a 100 s run 8,192 draws were replayed, **0 skipped, 0 without a colour target**, onto 4 distinct images. The two images the title
  presents are among them (about 530 draws each); the other two take 1,527 and 5,606 draws. So draws do reach the presented images, and
  those images still read back all zero: the draws write nothing visible (degenerate or discarded geometry, shaders that output zero,
  or empty vertex/constant data), not "the draws never reach the screen image".
  The same diagnostic also counts draws with no vertices or instances, an empty viewport, or an empty scissor: in the first 2,048 draws
  **none** of them, so the geometry call itself is well formed.
  Still open (not yet measured): depth test results, colour write masks, blend state, shader output values, and whether the vertex and
  constant data are filled (the log notes title memory with "no GPU copy").
  The existing local probe (`LEONIDA_LOCAL_DIAGNOSTICS=1`, `src/fsdraw_probe.h`) shows the first fullscreen draws: three-vertex draws
  with blending off and write mask 0xf, using the title's own shaders for the exe containers and a `PS_BlitColour` blit pass, into a
  1-target image that is *not* the presented one. The very first frame is presented straight after a clear to (0,0,0,0), before any
  draw, which explains frame 1 but not the later zero frames. Whether the scene images those blits read from are filled is the next question.
- Opus's advice (asked 2026-11-25) put "the draws write nothing" first and said to split it with a tint test. Two new off-by-default
  diagnostics: `LEONIDA_CLEAR_TINT=1` (every colour clear becomes opaque magenta) and `LEONIDA_FORCE_FIXED=<letters>`
  (`m` write mask all, `b` blending off, `d` depth and stencil off, `c` no culling, `1` all).
  - Tint on: both presented images stay **pure magenta** (mean 255,0,255 over all 8,294,400 texels) in every captured frame, so none of the
    draws changes a single pixel of them.
  - Forcing `m`+`b` together (first run: `1`, then the three-way split `m`/`d`/`c`): the images turn **black** from frame 61 on; forcing `d` or `c` alone
    leaves them magenta. So blob A's decoded blend or write mask is what keeps the draws from touching the image, and once it is
    out of the way the draws write zeros, so the pixel shaders' output (or their inputs) are zero as well. Both problems are real.
  - The split of `m` (write mask) from `b` (blending) was built and run but its lines were not captured (the diagnostics variable was missing in that
    shell), so which of the two it is is **not yet known**.
  - `LEONIDA_FSDRAW_POKE_CB=1` printed no POKE line, so that test did not run; it is inconclusive.
- **Correction, 2026-11-25 evening: it is not black after all; the earlier runs were simply too short.** A 10-minute run with the window
  restored and `LEONIDA_CAPTURE_EVERY=300` shows frames 1, 301 and 601 all zero, and **from frame 901 on a non-black picture**: a dark
  blue-grey screen with three button prompts at the bottom right ("Account picker", "Screen narration (off)", "Player"), identical in
  every later captured frame up to 8,401 (mean colour about 33, 33, 45). That is the title's own sign-in / profile screen, drawn with
  its real shaders and fonts, so draws, translated shaders, text and the presenter work end to end. My 100 s runs (541 frames) stopped just before the
  first drawn frame, and the "blob A blend keeps draws off the image" reading above was wrong in its conclusion: while the title was
  still loading it was drawing fades and blits of black. (The tint and force-state results themselves are real measurements.)
  The picture is static: it does not advance, so the title now waits on that screen (an account choice or an input), which is the next thing to look into.
  The sign-in screenshot is in `docs/screenshots/` (published at the owner's request); further captures and anything with game data stay local.
- **It moves on once it gets input (2026-11-25 evening, reported by the owner, not measured by me).** With input supplied by the owner, the title went through
  its first-run screens: Legal Notices (copyright), "Finish setup?" (controls note) and a "Navigation experience" page (minimap options). All are drawn
  by the recompiled title with its own shaders, fonts and textures; two screenshots are in `docs/screenshots/`. A third (the navigation page) is published with the owner's taskbar area painted over. The owner says the input was the **keyboard** in the title's window, and that it may have been very delayed (a low frame rate would explain a lag). Which keys, which build and whether it is the title reading the window's keyboard messages directly are not recorded yet: the build here has no SDL3, so no pad or keyboard pad is served.
- The owner then sent a further screenshot: the Rockstar logo on a dark background (the title's logo splash, after the setup screens), also drawn by the
  recompiled title. Kept local (it shows the owner's taskbar). So the boot path goes: sign-in screen, legal notices, finish setup, navigation options, logo.
- **Controller input works (2026-11-25 evening).** The runtime was rebuilt with SDL3 (`scripts\build_runtime.ps1 -FetchSdl3 -jobs 10`; downloads
  the pinned SDL 3.4.20 source once, hash-checked, with the owner's OK) and run with `LEONIDA_KEYBOARD_PAD=1`. The log shows `gameinput: SDL 3.4.20
  gamepads`, the keyboard pad attached and "connected Xbox One Controller (045e:02ff, player 1)"; the owner reports the controller moves the title
  along. The menu's runtime stage does not fetch SDL3, so a menu-built runtime has no pad (only upstream's `LEONIDA_INPUT_SCRIPT`).
  Earlier "keyboard" input before this build is unexplained (the docs say the title reads gamepads only).
- **Past the setup screens with scripted presses (2026-11-25 evening).** `LEONIDA_INPUT_SCRIPT` (A every 20 s from 90 s) with the SDL3 build takes the
  title through its setup screens to the loading screens: full-screen character artwork that fades in and out (kept local).
- **Crash at about 300 s, three runs in a row.** Run 1 (owner's controller) and run 2 (script): Vulkan device lost. With `LEONIDA_DEVICE_FAULT=1` the
  driver reported an invalid *write* address, while a compute dispatch on the compute queue and a copy on the direct queue were in flight. Run 3 skipped
  that compute program (`LEONIDA_SKIP_COMPUTE`) and ended instead with a null-pointer write inside the title.
- **Missing BCPack predictor file found and made.** Before each crash the trace held 189 DirectStorage reads failing with `E_DSTORAGE_DECOMPRESSION_ERROR`,
  and the log said "could not open the local BCPack predictor profile": `history.bcph` was never generated (the runtime stage of `make_game.py` makes it;
  our runtime was built by hand). Made locally with `tools\build_dstorage_history.py <dump> --out <work>\shaders\bcpack\history.bcph`, run inside the
  Visual Studio environment (it compiles a small helper with `cl`; about 3 minutes). With `LEONIDA_DSTORAGE_HISTORY` pointing at it the failures fell
  **from 189 to 5**, and the loading art shows.
- **Still crashing at about 300 s.** With the file in place: device lost again, now with 16 fault addresses of type 4 (instruction pointer, driver could not
  attribute them), so a shader that runs too long or never ends (a GPU hang, then Windows resets the GPU) is the leading guess. The title's null write
  follows the device loss, so it is a consequence. Just before, the frame rate fell from about 3 to 0 frames a second and one texture upload took 318 ms.
- **The crash is a GPU timeout reset.** Windows' System log has an `nvlddmkm` event 153 ("Error occurred on GPUID") at the moment of each of the four
  crashes, the NVIDIA driver's record of a GPU timeout and reset (Windows resets a GPU whose work runs past about 2 s). Skipping the four compute programs
  dispatched most often before the hang changed nothing (same loss, same time). Still open: is the work merely too slow (frames fall to 0-3 a second before
  it) or a shader that never finishes? Raising the Windows GPU timeout for one test would tell the two apart.
- **With a 60 s GPU timeout (owner set `TdrDelay`/`TdrDdiDelay` = 60 and rebooted, for testing only) the device is no longer lost**, so the GPU work
  was slow, not endless. The run still ended at about 254 s, now plainly: the title stops itself on purpose. The faulting instruction is a deliberate
  write to address 0 in the title's own fatal-error path, reached from a thread that behaves like the title's hang watchdog (upstream's docs/xdxr.md
  describes a ~30 s startup watchdog). In the same run, 37 compute pipelines were compiled on first use, **187 s of compiling in all** (one took 7 s),
  and one stretch shows 40 submissions in 21.8 s. Leading explanation: first-use pipeline compiles stall the title past its watchdog. The fix to try is
  the `pipelines` stage of `make_game.py`, which compiles every pipeline ahead of time into `pipeline_cache.bin`.
- **151 more pixel shaders translate (2026-11-25 evening).** They had been refused because llvm-mc's decoder drops one VOP3 bit of
  `v_interp_p2_f16` (bit 14, the op_sel bit that sends the result to the high half of the register); the translator's encoding check caught the
  mismatch (Opus found and explained it). `tools/rdna2spirv.py` now restores that bit (`restore_interp_p2_f16_dst_hi`, only when it is the sole
  difference) and writes the high half (`write_half16`). All 151 now translate and pass `spirv-val`; they are merged into the local library
  (11,255 of 11,339 graphics programs; the remaining 84 are 78 "DPP on v_cmpx" and 6 without a shader container). New test:
  `tests/test_interp_p2_f16_dst_hi.py` (synthetic encodings). Not yet checked on the GPU against hardware results.
- **Build: the graphics pipeline library is now a step of the shaders stage** (`graphics_library_shaders` in `make_game.py`): `shader_library.py`
  with `--stages vs,ps --disasm --carve`, then the usual sharded translation into `<work>\shaders\spirvspx_gfx`, rebuilt when shaders.rpf,
  the tools, llvm-mc or the translator change. So a menu build no longer needs the manual commands above. Stage tests updated and passing
  (bvh, exe, fspx, library, argparse, dry run, empty translation, resume, translator flags). Not yet run end to end (about 50 minutes).
- **Correction:** the menu already asks for SDL3 (controller support) and the runtime stage already builds the BCPack predictor file; both
  were missing here only because this runtime was built by hand. The onboarding guide said otherwise and is fixed.
- **Banana window and fps counter.** With the presenter on, the title's window now has a banana-yellow border and caption (Windows 11 DWM
  colours) and the caption reads "🍌 Banana Theft Auto 🍌  N fps", refreshed twice a second from the frames actually presented
  (`start_banana_frame` in `runtime/shims/d3d12_xs.cpp`; `LEONIDA_BANANA_FRAME=0` turns it off). Seen working: 7.5-8.5 fps on the setup screens
  while the compute pre-compile was running in the background. The title's window class is ANSI, so the caption is stored with
  `DefWindowProcW`, or the bananas would show as "??".
Next: see why the title waits on the sign-in screen (input? account?). The earlier question, why draws wrote nothing, is answered: it was loading time.
 (their pipelines' shader tier, the vertex and constant data they read).

### Things that were wrong along the way (kept for honesty)
- First guess for the failing `Close` calls: reopen lists when their allocator is reset. It reopened nothing; removed.
- First reading of the extra window: "not part of the run". It belongs to the game itself (the title's own window).
- A first reading of thread-stack dumps as a polling loop: the frame was an infinite wait and the CPU figure cumulative.
- The first CLZERO fix (one `VirtualQuery` per region, not per page) did not reduce that thread's CPU use; remembering the writable span did.
