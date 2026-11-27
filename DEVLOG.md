# Dev log

How Banana Theft Auto got from "crashes after 3 seconds" to "loading the world": each problem we hit, how we tracked it
down, and what it changed. The facts here are measured on one PC (RTX 3090). Working details (code locations, settings, game
internals) stay private, and nothing from the game is published.

## How we work

- **Measure, don't guess.** Every step is backed by a test run, a count or a captured frame. When something is a guess,
  we say so.
- **One change at a time.** Short scripted test runs, each with a one-line result.
- **New behaviour starts switched off.** Experiments are opt-in until they've proven themselves, so normal runs stay the same.
- **Other projects are leads, not code.** We read what upstream Leonida and similar projects found, then write our own fix.
  Nothing is merged automatically.
- **Wrong turns stay in the record.** When we misread something, we write down the correction.

---

## 2026-11-24: Setting up

- **No build environment.** The PC was missing the Vulkan SDK, the LLVM tools and the C++ compiler, and the system drive was
  too small for a full build (about 400 GB). We wrote the guided menu (`Leonida.bat`), which checks the PC, finds your copy
  of the game, offers to install the tools (asking first) and starts the build.
- **One upstream merge, then hands off.** Leonida was merged in once. From then on, upstream changes are only brought in by
  hand.

## 2026-11-25: From a crash at 3 seconds to the first picture

1. **A third of the shaders wouldn't translate.** The standard disassembler choked on part of the game's shader library.
   Counting the failures showed that most were variants of one shader. A fallback decoder took us **from 1,685 to 2,615
   translated programs**. A small change to how the disassembler is fed also made it about 300 times faster on large shaders.
2. **The game crashed 3 seconds in.** We logged every graphics call the game made and found the ones it couldn't get
   answered. Answering them one at a time took it from **1,655 calls and a crash to a steady window**. One guess (reopening
   command lists) did nothing, so we removed it.
3. **One thread was burning a CPU core.** A stack profile showed most of its time went into a single memory check. Caching
   that check removed the cost.
4. **No draws at all.** The game asked for its graphics pipelines tens of thousands of times and never got one, so it never
   drew anything. Upstream had solved this, and with the owner's OK we merged that part in. Draws went **from 0 to over
   2,000**.
5. **Graphics shaders were missing, then out of date.** We translated the graphics part of the library (11,104 programs
   passed validation, later 11,255) and retranslated the game's own shaders. After that **every graphics pipeline the game
   asked for was created: over 25,000, none failed.**
6. **The window stayed black.** We captured frames, tinted the clears and forced render states, and built a theory about
   blending. **The theory was wrong:** the test runs were simply too short. A 10-minute run showed **the sign-in screen**,
   the first picture drawn by the recompiled game. Lesson: let it load before judging the screen.
7. **Stuck on the sign-in screen.** It wanted input. With controller support built in, it moved through legal notices,
   setup, navigation options, the logo and the loading artwork.
8. **A crash at about 5 minutes.** A missing data file made streamed textures fail to decompress. Generating it cut the
   failures from 189 to 5, and the loading art appeared. The crash stayed. Windows' event log showed the graphics driver
   being reset after a timeout. Giving the GPU more time proved the work was slow, not stuck. What remained was **the game's
   own hang watchdog** stopping itself, because shaders were being compiled while it ran.

## 2026-11-26: Past the watchdog, into the world

9. **Pre-compiling shaders, three tries.** The plan was to compile every pipeline ahead of time so the game never waits.
   - **Try 1** built every game pipeline (4.7 GB, about 9 hours), but it didn't help. The slow ones come from a separate
     shader library this step never touches.
   - **Try 2** compiled that library too, and it **still missed**. The pre-compiler built each pipeline slightly differently
     from the game, so the driver treated them as different. The same shaders took a fraction of a second there and several
     seconds in the game.
   - **Try 3** compiled them inside the game's own runtime, exactly as the game builds them (hours of compiling). The game
     ran longer, but some stalls remain. That part is parked for now.
   - Lesson: a cache only helps if it's built exactly the way the game will ask for it.
10. **Two stalls inside our own runtime.** Thread stack dumps every few seconds showed a lock taken twice, and a wait with
    no time limit. Both are fixed.
11. **Workarounds before more compiling.** Following the owner's call to try quick fixes first, we dealt with the game's
    hang checks so a long stall no longer ends the run. Result: **the first full 15-minute run without a crash, and the game
    went on into loading the world.**
12. **A memory bug while streaming.** Two crashes during the world load came from our runtime replacing memory the game had
    mapped itself. Upstream had found the same thing. We wrote our own fix, and it stepped in 16 times in the next run.
13. **A missing upscaler shader.** A crash at about 4 minutes came from one shader the upscaler needed that had never been
    translated. Fixing three gaps in our disassembler and translator got **all 29 of the upscaler's shaders translating**,
    and the run went past that point.
14. **The "assertion" that wasn't.** A new stop looked like a failed check in the game. Reading the game's code showed it's
    the game's reaction to **the graphics card hanging**. The driver's fault report pointed at a short chain of compute
    shaders that run when the world starts. Upstream lists the same stop as unsolved. **This is what we're working on now.**

---

## Where it stands

- **Works:** boot, all screens up to the loading art, controller input, 15-minute runs, getting into the world load.
- **Working on:** the graphics card hang at the start of the world load.
- **Next:** the first world picture, then speed. The menus run at about 8.5 fps, the world load at well under 1 fps, and the
  goal is 30.

## Lessons so far

- Short test runs lie. Let the game load before judging what's on screen.
- When the game "crashes", find out why it stopped. It's often the game stopping itself on purpose.
- A shader cache must match the game's own requests exactly.
- Save long jobs' progress in pieces, so an interruption costs minutes, not hours.

*Grand Theft Auto and all related names are trademarks of their owners. Unofficial fan project, not affiliated with Rockstar
Games or Take-Two.*
