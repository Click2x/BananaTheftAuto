# Getting started on Banana Theft Auto (for a new helper)

This is a step-by-step for someone new to the project. Do the steps in order; stop and ask when a check fails.
Where we are today is in **[PROGRESS.md](../PROGRESS.md)** (read its last section first).

## Where the project stands (one paragraph)
Banana Theft Auto recompiles the Xbox build of GTA VI (1.0.2.1) to run on Windows with Vulkan. The title now starts, runs
steadily, creates every graphics pipeline it asks for and records thousands of draws, **but the window is black**: the images
it presents are all zero, even though draws land on them. Finding out why is the current job.

## Rules (please keep them)
- You need your own legal copy of the game dump. **Never** put game files, shader outputs, disassembly or byte offsets into the
  repository, an issue, a chat or a screenshot. Logs, shaders and extracted data stay in your local work folder.
- Push only to the project's own repository (`bta` remote, branch `main`) and only small, working steps with a clear message.
  Nothing is pulled from the upstream Leonida project automatically; the owner decides what to take from it.
- Write down what you measured, including what turned out wrong. Add it to `PROGRESS.md`.

## Step 1. Tidy your folders
A folder layout that avoids mix-ups (one place per thing):

| Folder | What it is |
|---|---|
| `T:\CL GTA6\GTA6.Xbox.v1.0.2.1-MYDUMP` | the game dump. Read only. Do not edit or copy out of it. |
| `T:\CL GTA6\BananaTheftAuto` | the project code (Step 3). All your work happens here. |
| `T:\CL GTA6\work` | local outputs: translated shaders, run logs, captures (Step 5). Never committed. |
| `T:\CL GTA6\BTA` | the built game folder (Step 6). |

The older folders (`Leonida`, `Leonida Continued`, `GTA6-Leonida`, `Leonida-WorkingDir`, `early_xmas`) are copies of the upstream
project from before our changes. Leave them alone, do not work in them, and delete them later only once everything runs from the new place.
**Check the dump's version:** it must be 1.0.2.1 (the folder name says so).

## Step 2. Install only Python and Git (the menu does the rest)
1. [Python 3.12 or newer](https://www.python.org/downloads/): tick "Add python.exe to PATH". Check: `python --version`.
2. [Git for Windows](https://git-scm.com/download/win). Check: `git --version`.

Everything else (Vulkan SDK, Visual Studio C++ tools, `llvm-mc` with AMDGPU, ffmpeg) is offered by the menu in Step 5, one item or
all at once, and nothing is installed without a yes. A Windows administrator prompt may appear for the C++ tools; the `llvm-mc`
build takes 20-40 minutes. You do **not** need the `clang+llvm-...aarch64` folder (it is the ARM64 build, the wrong kind for an x64 PC); leave it unused.
You need a GPU with Vulkan 1.3 and current drivers (the project is developed on an RTX 3090).

## Step 3. Get the code
```powershell
cd "T:\CL GTA6"
git clone https://github.com/Click2x/BananaTheftAuto BananaTheftAuto
cd BananaTheftAuto
git submodule update --init --recursive
git remote -v
```
The owner must first add you as a collaborator on that repository (GitHub, Settings, Collaborators) so you can push.
Work on your own branch: `git switch -c yourname/what-you-do`, then merge to `main` only when the owner says so.

## Step 4. Read, in this order (about an hour)
1. `README.md` (status table at the top, prerequisites).
2. `PROGRESS.md` (the last three sections: what was measured, what is open).
3. `docs/boot.md`, then `docs/d3d12_vulkan.md` section 4.5 (how a frame is presented).
Keep a list of words you do not know; ask.

## Step 5. Build with the menu
From `T:\CL GTA6\BananaTheftAuto`, double-click `Leonida.bat`.
1. When it asks for the game, choose or paste `T:\CL GTA6\GTA6.Xbox.v1.0.2.1-MYDUMP` (the folder that holds `MicrosoftGame.Config`).
2. At "What the build needs", say yes to each missing tool (see Step 2).
3. Choose the output and work folders under `T:\CL GTA6` (`BTA` and `work`) rather than the default `Documents\Leonida`.
4. Build the **shaders** and **runtime** stages. The shader step takes about 40 minutes and uses tens of GB of disk. That is normal. A stopped build continues where it left off.
Check: `T:\CL GTA6\BTA\gta6rt.exe` exists and the work folder has a `shaders` folder.
Prefer a terminal? The same build is `python -I make_game.py --game "<dump>" --work "T:\CL GTA6\work" --out "T:\CL GTA6\BTA" --stages check,shaders,runtime --jobs 8 --no-tui`.
The extra graphics-shader step is not in the menu yet; the owner will say when to do it.

## Step 6. Run the title and look at the logs
```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_logged.ps1 -Port "T:\CL GTA6\BTA" -LogRoot "T:\CL GTA6\work\runlogs" -Experiments -TitleWindow -TimeoutSec 90
```
Open `summary.txt` in the newest `run-...` folder. Expect: no crash, "still running at the time limit", thousands of D3D12 calls.
The title's window appears **minimised**. Restore it from the taskbar (a minimised window cannot be presented into).
**Getting past the first screens needs a controller (or the keyboard pad), and a runtime built with SDL3.** The menu's runtime stage does
not include SDL3, so after Step 5 rebuild the runtime once with it (this downloads the pinned SDL 3.4.20 source, about 10 MB, hash-checked):
```powershell
cd "T:\CL GTA6\BananaTheftAuto"
powershell -ExecutionPolicy Bypass -File scriptsuild_runtime.ps1 -FetchSdl3 -jobs 8
copy runtimeuild\gta6rt.exe "T:\CL GTA6\BTA\"
copy runtimeuild\gta6rt_tls_host.dll "T:\CL GTA6\BTA\"
```
Plug in a controller before starting, restore the title's window, wait several minutes for loading, then press A. For the keyboard pad set `LEONIDA_KEYBOARD_PAD=1`
(arrows = d-pad, Enter = A, Backspace = B, Esc = Menu). The log should say `gameinput: SDL 3.4.20 gamepads`.
To save what the title presents: set `LEONIDA_CAPTURE=<an empty folder>` and `LEONIDA_CAPTURE_SOURCE=1` before the run; files
`frame_*.ppm` and `source_*.ppm` appear. At the moment they are all black. That is the problem.

## Step 7. Your first task
Pick one, tell the owner which, and write the result in `PROGRESS.md`:
- **A. Reproduce.** Do Step 6 on your PC and confirm the black frames and the `LEONIDA_DRAW_STATS=1` summary lines. (Easy, and proves your setup.)
- **B. Find why the draws write nothing.** Open questions: depth test results, shader output values, whether vertex and constant data are filled. Start from
  `runtime/src/vulkan_replay.h` (search `LEONIDA_DRAW_STATS`) and `runtime/src/fsdraw_probe.h`.
- **C. Build step for the graphics shader library** so it needs no manual commands (see "Next steps" in `PROGRESS.md`).

## When something fails
Copy the last 40 lines of `summary.txt` (not game data) to the owner. Do not retry the same thing ten times; write what you tried.
