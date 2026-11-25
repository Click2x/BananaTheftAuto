# Getting started on Banana Theft Auto (for a new helper)

This is a step-by-step for someone new to the project. Do the steps in order; stop and ask when a check fails.
Where we are today is in **[PROGRESS.md](../PROGRESS.md)** (read its last section first).

## Where the project stands (one paragraph)
Banana Theft Auto recompiles the Xbox build of GTA VI (1.0.2.1) to run on Windows with Vulkan. The title now loads, draws its own
screens (sign-in, legal notices, setup, loading art), takes controller input, and then stops itself after about 4-5 minutes, while it is still
loading. The current job is getting past that point. The **progress tracker** at the top of the [README](../README.md) is the short version;
[PROGRESS.md](../PROGRESS.md) is the full log.

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
4. Build **Run the port** (shaders and runtime). The shader step takes about 40 minutes and uses tens of GB of disk. That is normal. A stopped build continues where it left off.
5. When it asks about **controller support**, say yes. The build then downloads the pinned SDL 3.4.20 source once (about 10 MB, hash-checked).
   Without it the title never gets past its sign-in screen.
The runtime stage also makes the BCPack predictor file (`work\shaders\bcpack\history.bcph`, about 3 minutes); the runtime finds it by itself.
Check: `T:\CL GTA6\BTA\gta6rt.exe` exists and the work folder has a `shaders` folder.
**Already built before controller support was in the menu, or pulled new code?** Choose Start, then **Runtime only**: it rebuilds
`gta6rt.exe` (asking about controller support) without redoing the shaders.
Prefer a terminal? The same build is `python -I make_game.py --game "<dump>" --work "T:\CL GTA6\work" --out "T:\CL GTA6\BTA" --stages check,shaders,runtime --fetch-sdl3 --jobs 8 --no-tui`.
The extra graphics-shader step is not in the menu yet; the owner will say when to do it.

## Step 6. Run the title with the menu
Plug in a controller first. In `Leonida.bat` choose **Run the game**. It asks whether to use the keyboard as a pad (arrows = d-pad,
Enter = A, Backspace = B, Esc = Menu) and how many minutes to run (15 is fine), then starts the title with logging.
1. The title's window opens **minimised**. Restore it from the taskbar (a minimised window is never drawn into).
2. Wait. It stays black, then grey, for several minutes while it loads.
3. When the sign-in screen shows its button prompts at the bottom right, press **A** (Enter on the keyboard pad). The frame rate is
   very low: press once and wait a few seconds before pressing again.
4. Go on through Legal Notices, Finish setup and Navigation options. The logo and the loading art follow. That is as far as anyone has got.
When it ends, the summary is printed; it is also `summary.txt` in the newest `run-...` folder under `T:\CL GTA6\work\runlogs`.
Its notable lines should include `gameinput: SDL 3.4.20 gamepads`. If they don't, the runtime was built without controller support:
choose Start, then Runtime only, and say yes to controller support.
The same run from a terminal:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_logged.ps1 -Port "T:\CL GTA6\BTA" -LogRoot "T:\CL GTA6\work\runlogs" -Experiments -TitleWindow -TimeoutSec 900
```
To save what the title presents: set `LEONIDA_CAPTURE=<an empty folder>` and `LEONIDA_CAPTURE_SOURCE=1` before the run; files
`frame_*.ppm` and `source_*.ppm` appear. Keep them local.

## Step 7. Your first task
Pick one, tell the owner which, and write the result in `PROGRESS.md`:
- **A. Reproduce.** Do Step 6 on your PC and confirm you reach the loading art and the crash at about 300 s. Note your GPU and how long each screen took. (Easy, and proves your setup.)
- **B. Find the GPU hang.** Which shader or dispatch is running when the device is lost (`LEONIDA_DEVICE_FAULT=1`); see the last entries of `PROGRESS.md`.
- **C. Build step for the graphics shader library** so it needs no manual commands (see "Next steps" in `PROGRESS.md`).

## When something fails
Copy the last 40 lines of `summary.txt` (not game data) to the owner. Do not retry the same thing ten times; write what you tried.
