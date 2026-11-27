# 🍌 Tools behind Banana Theft Auto

Everything we've used to build, test and share the project so far. All of it is free, open source or part of a standard
Windows development setup. None of it ships game files.

## The machine

| | |
|---|---|
| OS | Windows 11 Pro |
| Graphics | NVIDIA GeForce RTX 3090 (24 GB), driver 621.01 |
| Game | your own copy of GTA VI for Xbox Series, package 1.0.2.1 |

## Building

| Tool | Used for |
|---|---|
| **Visual Studio 2022** (MSVC C++ compiler) | building the runtime (`gta6rt.exe`) |
| **CMake** + **Ninja** | the runtime's build system |
| **Vulkan SDK 1.4.363.0** | Vulkan headers, `spirv-val` shader validation, `glslangValidator` |
| **SDL3** | controller and keyboard input |
| **Python 3.12** | the build menu, the shader translation pipeline and the test tooling |
| **LLVM `llvm-mc` 21** | reading the console GPU's shader code |
| **Git** + **GitHub** | version control and this repository |

## Graphics and shaders

| Tool | Used for |
|---|---|
| **Vulkan** | the graphics API the game runs on, on PC |
| **SPIR-V** | the shader format the console shaders are translated into |
| **The Leonida shader translator** (Python, with our fixes) | console GPU shaders to Vulkan shaders |
| **NVIDIA's Vulkan driver** | compiling and caching the translated shaders |

## Testing and debugging

| Tool | Used for |
|---|---|
| **PowerShell** + **Git Bash** | scripted test runs with logs, time limits and scripted controller presses |
| Run logs, frame captures and the driver's device-fault reports | seeing what each test run did and where it stopped |
| **Capstone** (disassembly library) | local debugging |
| **Windows Event Viewer** | spotting graphics driver resets |

## Pictures, promo and community

| Tool | Used for |
|---|---|
| **Pillow** (Python imaging) | screenshots, the watermark and the update cards |
| **CairoSVG** | rendering the banner, the watermark and the "where we are" graphic |
| **Tkinter** (Python) | the on-screen watermark, the work log panel, the ETA countdown and the game-completion tracker |
| **Windows notifications** | the live "what we're doing now" status |
| **Discord** | the Part Time Heroes community, where the build is streamed live |

## AI assistance

| Tool | Used for |
|---|---|
| **Claude Code** (Anthropic), desktop app | writing and testing code, running the test loop, docs and updates |
| **Claude Opus** agents | research, such as reviewing new changes in related projects |
| A shared project board | coordinating the two AI coding agents that work in this repository |

## Built on

- **Leonida**, the open-source static recompilation of GTA VI's Xbox build to Windows/Vulkan, and the earlier projects
  it continues (see Credits in the README).
- Related projects for the same game were read for ideas only; no code was taken from them.

💬 Watch the build live: https://discord.gg/ppNRZDSda · 📂 https://github.com/Click2x/BananaTheftAuto
