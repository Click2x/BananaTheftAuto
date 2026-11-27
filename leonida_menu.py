# Local addition to this fork (not part of upstream): Leonida's guided terminal menu.
# Standard library only. Start it with Leonida.bat or `py -I leonida_menu.py`.
#
# It draws and asks; the work is make_game.py's, started as a separate process so its own build board keeps working.
# Nothing is downloaded or installed without a yes. Choices (paths and numbers, no secrets) are kept in
# %LOCALAPPDATA%\Leonida\settings.json. `--preview` draws the screens once, asking nothing and building nothing.
import collections
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import textwrap
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import make_game as mg  # noqa: E402  (importing it runs nothing; main() is guarded)
import bta_update  # noqa: E402  (Banana Theft Auto: Update)
import bta_buildcheck  # noqa: E402  (Banana Theft Auto: Check my build)

DATA = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Leonida")
SETTINGS = os.path.join(DATA, "settings.json")
LOG_DIR = os.path.join(DATA, "logs")
DOCS_OUT = os.path.join(os.path.expanduser("~"), "Documents", "Leonida")
MIN_RAM_GB = 16   # a comfort suggestion of this menu, not a number from upstream
ANSI = re.compile(r"\x1b\[[0-9;]*m")
T = None

# preset key -> (stages, label, hint, free GB the stages need (upstream's estimate))
PRESETS = {
    "1": ("check,shaders,runtime", "Run the port", "shaders + runtime, no asset export", 30),
    "2": ("check,shaders,assets,runtime", "Full build", "also exports every asset", 400),
    "3": ("check,shaders", "Shaders only", "translate the GPU programs", 30),
    "4": ("check", "Check game files only", "reads sizes, builds nothing", 0),
    "5": ("check,shaders,runtime,pipelines", "Port + GPU pipelines", "also compiles every pipeline for your GPU; hours", 35),
    "6": ("check,runtime", "Runtime only", "rebuild gta6rt.exe after an update; shaders already built", 1),
}
MEM_PER_JOB_GB = 2   # this menu's planning estimate for one job, not a measured figure

# winget installs: id -> (label, winget args, stage that needs it, source, what it is)
WINGET = {
    "dotnet": (".NET 8 SDK", ["--id", "Microsoft.DotNet.SDK.8", "-e"], "assets", "winget (Microsoft)", "builds the asset reader"),
    "vulkan": ("Vulkan SDK", ["--id", "KhronosGroup.VulkanSDK", "-e"], "shaders", "winget (Khronos)", "spirv-as and spirv-val"),
    "vs": ("Visual Studio 2022 Build Tools (C++)",
           ["--id", "Microsoft.VisualStudio.2022.BuildTools", "-e", "--override",
            "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"],
           "runtime", "winget (Microsoft)", "the C++ compiler for the runtime; asks for administrator rights"),
    "ffmpeg": ("ffmpeg", ["--id", "Gyan.FFmpeg", "-e"], "wav", "winget (Gyan)", "only for decoding audio to WAV"),
}


class Quit(Exception):
    pass


# --------------------------------------------------------------------------------------------------- the look
# Inspired by GTA VI: a deep night-purple panel, hot-pink frame, a sunset that runs pink > orange > gold, a teal
# accent for keys, and wanted-level stars for the requirements.

PANEL, FRAME, PLATE, PLATE_HI = 53, 205, 90, 198
CREAM, LAVENDER, TEAL, GOLD, GREEN, RED, DIMSTAR = 230, 183, 51, 220, 48, 203, 240
SUNSET = (53, 89, 125, 161, 197, 203, 209, 215, 221)   # the strip under the title
TITLE_GRAD = (199, 205, 204, 209, 214, 220)


def _enable_vt():
    if os.name != "nt":
        return True
    try:
        k = ctypes.windll.kernel32
        k.GetStdHandle.restype = ctypes.c_void_p
        k.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        k.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        h = k.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        return bool(k.GetConsoleMode(h, ctypes.byref(mode)) and k.SetConsoleMode(h, mode.value | 0x0004))
    except (OSError, AttributeError):
        return False


class Term:
    def __init__(self):
        out = sys.stdout
        self.tty = bool(getattr(out, "isatty", lambda: False)())
        self.color = not os.environ.get("NO_COLOR") and (os.environ.get("LEONIDA_COLOR") == "1" or (self.tty and _enable_vt()))
        enc = (getattr(out, "encoding", None) or "").lower()
        self.uni = "utf" in enc and not os.environ.get("LEONIDA_ASCII") and (
            os.environ.get("LEONIDA_UNICODE") == "1" or os.name != "nt" or bool(os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM")))
        g = self.uni
        self.s = dict(ok="\u2713" if g else "OK", bad="\u2717" if g else "X", warn="!", arrow="\u203a" if g else ">", dot="\u2022" if g else "*",
                      tl="\u256d" if g else "+", tr="\u256e" if g else "+", bl="\u2570" if g else "+", br="\u256f" if g else "+",
                      h="\u2500" if g else "-", v="\u2502" if g else "|", full="\u2588" if g else "#", empty="\u2591" if g else ".",
                      marker="\u25b6" if g else ">", star="\u2605" if g else "*", star0="\u2606" if g else ".",
                      updown="\u2191\u2193" if g else "Up/Down", back="\u25c2" if g else "<", strip="\u2580" if g else "=")

    def width(self):
        return max(56, min(shutil.get_terminal_size((90, 24)).columns - 4, 100))


def init():
    global T
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    T = Term()
    return T


def paint(text, fg=None, bg=None, bold=False):
    if not T.color:
        return text
    codes = (["1"] if bold else []) + (["38;5;%d" % fg] if fg is not None else []) + (["48;5;%d" % bg] if bg is not None else [])
    return ("\x1b[" + ";".join(codes) + "m" + text + "\x1b[0m") if codes else text


def c(text, fg=None, bold=False):
    return paint(text, fg, None, bold)


def vlen(s):
    return len(ANSI.sub("", s))


def wrap(text, width, indent=""):
    return textwrap.wrap(text, width, initial_indent=indent, subsequent_indent=indent) or [""]


def p(text=""):
    print(text, flush=True)


def panel_width():
    return min(T.width(), 66)


def panel_inner():
    return panel_width() - 4


def prow(*segs):
    """The inside of one panel row: (text, fg, bg, bold) segments on the purple, cut and padded to the inner width."""
    n, out, used = panel_inner(), "", 0
    for s in segs:
        text = s[0][:max(0, n - used)]
        out += paint(text, s[1] if len(s) > 1 else None, s[2] if len(s) > 2 and s[2] is not None else PANEL, s[3] if len(s) > 3 else False)
        used += len(text)
    return out + paint(" " * (n - used), None, PANEL)


def pframe(content):
    v = T.s["v"]
    return "  " + paint(v, FRAME, PANEL) + paint(" ", None, PANEL) + content + paint(" ", None, PANEL) + paint(v, FRAME, PANEL)


def ptop():
    return "  " + paint(T.s["tl"] + T.s["h"] * (panel_width() - 2) + T.s["tr"], FRAME, PANEL)


def pbot():
    return "  " + paint(T.s["bl"] + T.s["h"] * (panel_width() - 2) + T.s["br"], FRAME, PANEL)


def sunset_row():
    n = panel_inner()
    if not T.color:
        return prow((T.s["strip"] * n,))
    cells = len(SUNSET)
    return "".join(paint(T.s["strip"], SUNSET[min(cells - 1, i * cells // n)], PANEL) for i in range(n))


def gradient(text, colors):
    if not T.color:
        return text
    return "".join(paint(ch, colors[min(len(colors) - 1, i * len(colors) // max(1, len(text)))], PANEL, True) for i, ch in enumerate(text))


def banner():
    p()
    p(ptop())
    p(pframe(prow()))
    title = "L E O N I D A"
    pad = " " * ((panel_inner() - len(title)) // 2)
    p(pframe(paint(pad, None, PANEL) + gradient(title, TITLE_GRAD) + paint(" " * (panel_inner() - len(pad) - len(title)), None, PANEL)))
    p(pframe(prow()))
    p(pframe(sunset_row()))
    p(pframe(prow((" Grand Theft Auto VI, built from your own copy", CREAM))))
    for line in ("built on ubiquitarianism/leonida", "GPL-3.0  " + T.s["dot"] + "  not affiliated with Rockstar Games or Take-Two"):
        p(pframe(prow((" " + line, LAVENDER))))
    p(pbot())


def heading(text, step=None):
    p()
    label = ("Step %d of %d  %s  " % (step[0], step[1], T.s["arrow"]) + text) if isinstance(step, tuple) and step[1] > 1 else text
    p("  " + paint(label, FRAME, None, True))
    p("  " + paint(T.s["h"] * min(vlen(label), T.width() - 2), 97))


def line(state, text, detail=""):
    sym, col = {"ok": (T.s["ok"], GREEN), "bad": (T.s["bad"], RED), "warn": (T.s["warn"], GOLD), "info": (T.s["dot"], LAVENDER)}[state]
    p("   " + paint(sym, col, None, True) + "  " + text + (paint("   " + detail, 245) if detail else ""))


def note(text):
    for l in wrap(text, T.width() - 6):
        p("   " + paint(l, 245))


def ask(label, default=None, path=False):
    shown = (" [" + str(default) + "]") if default not in (None, "") else ""
    try:
        s = input("  " + paint(label, None, None, True) + paint(shown, 245) + paint(" " + T.s["arrow"] + " ", FRAME))
    except EOFError:
        raise Quit()
    s = s.strip()
    if path:
        s = s.strip('"').strip("'").strip()
    return s if s else (default if default is not None else "")


def yesno(label, default=False):
    d = "Y/n" if default else "y/N"
    while True:
        s = ask(label + " (" + d + ")").lower()
        if not s:
            return default
        if s in ("y", "yes"):
            return True
        if s in ("n", "no"):
            return False
        p("   " + paint("Please answer y or n.", GOLD))


def pause(text="Press Enter to go back to the menu"):
    try:
        input("  " + paint(text + " ", 245))
    except EOFError:
        raise Quit()


def shorten(text, n):
    if len(text) <= n:
        return text
    dots = "\u2026" if T.uni else "..."
    keep = max(1, n - len(dots))
    return text[:keep // 2] + dots + text[-(keep - keep // 2):]


def tail(text, n):
    return text if len(text) <= n else ("\u2026" if T.uni else "...") + text[-(n - 1):]


def box(lines, title=None, tone=FRAME):
    w = T.width()
    inner = w - 4
    s = T.s
    out = []
    for l in lines:
        out += wrap(ANSI.sub("", l), inner) if vlen(l) > inner else [l]
    label = (" " + title + " ") if title else ""
    p("  " + paint(s["tl"] + s["h"] + label + s["h"] * max(0, w - 3 - len(label)) + s["tr"], tone, None, True))
    for l in out:
        p("  " + paint(s["v"], tone) + " " + l + " " * max(0, inner - vlen(l)) + " " + paint(s["v"], tone))
    p("  " + paint(s["bl"] + s["h"] * (w - 2) + s["br"], tone))


# ---------------------------------------------------------------------------------------- arrow-key panel menus

def item_rows(groups, idx):
    labels = [lab for g in groups for _, lab, _ in g]
    plate_w = max(22, min(max((len(l) for l in labels), default=0) + 3, panel_inner() - 12))
    rows, n = [], 0
    for gi, group in enumerate(groups):
        for ii, (key, label, hint) in enumerate(group):
            if ii:
                rows.append(prow())
            elif gi:
                rows.append(prow((" " + T.s["h"] * (panel_inner() - 2), FRAME)))
            sel = n == idx
            plate = (" " + shorten(label, plate_w - 1)).ljust(plate_w)
            beside = panel_inner() - 5 - plate_w - 2
            under = bool(hint) and len(hint) > beside
            rows.append(prow((" " + key[:1] + " ", LAVENDER), ((T.s["marker"] if sel else " ") + " ", TEAL, None, True),
                             (plate, 231 if sel else 225, PLATE_HI if sel else PLATE, sel), (("  " + hint) if hint and not under else "", LAVENDER)))
            if under:
                rows.append(prow((" " * 6 + shorten(hint, panel_inner() - 7), LAVENDER)))
            n += 1
    return rows


def render_panel(title, groups, idx, extra=None, keys_mode=True):
    lines = [ptop(), pframe(prow())]
    if title:
        lines += [pframe(prow((" " + title, CREAM, None, True))), pframe(prow())]
    lines += [pframe(e) for e in (extra or [])]
    if extra and groups:
        lines.append(pframe(prow()))
    lines += [pframe(r) for r in item_rows(groups, idx)]
    lines += [pframe(prow()), pbot()]
    if groups:
        if keys_mode:
            lines.append("   " + paint(T.s["updown"] + " Move   Enter - Select   ", TEAL) + paint("Esc - Back", TEAL))
        else:
            lines.append("   " + paint("Type the number or letter of your choice, then Enter", TEAL))
    return lines


def keys_available():
    return os.name == "nt" and bool(T.color) and bool(sys.stdin) and sys.stdin.isatty() and os.environ.get("LEONIDA_KEYS") != "0"


def read_key():
    import msvcrt
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        return {"H": "up", "P": "down", "G": "home", "O": "end"}.get(msvcrt.getwch(), "")
    if ch in ("\r", "\n"):
        return "enter"
    if ch == "\x1b":
        return "esc"
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch


def _redraw(out, n, lines):
    out.write("\x1b[%dA" % n + "".join("\r\x1b[2K" + l + "\n" for l in lines))
    out.flush()


def select_menu(title, groups, default=None, extra=None):
    flat = [it for g in groups for it in g]
    keys = [k.lower() for k, _, _ in flat]
    idx = keys.index(default.lower()) if default and default.lower() in keys else 0
    if not keys_available():
        for l in render_panel(title, groups, -1, extra, keys_mode=False):
            p(l)
        p()
        while True:
            ans = ask("Choose", flat[idx][0]).lower()
            if ans in keys:
                return flat[keys.index(ans)][0]
            p("   " + paint("Please type one of: " + ", ".join(k for k, _, _ in flat), GOLD))
    out = sys.stdout
    out.write("\x1b[?25l")
    try:
        lines = render_panel(title, groups, idx, extra)
        n = len(lines)
        out.write("".join("\r\x1b[2K" + l + "\n" for l in lines))
        out.flush()
        while True:
            k = read_key()
            if k == "enter":
                break
            if k == "esc":
                cancel = next((i for i, key in enumerate(keys) if key in ("b", "q", "c", "x")), None)
                if cancel is None:
                    continue
                idx = cancel
                _redraw(out, n, render_panel(title, groups, idx, extra))
                break
            if k == "up":
                idx = (idx - 1) % len(flat)
            elif k == "down":
                idx = (idx + 1) % len(flat)
            elif k == "home":
                idx = 0
            elif k == "end":
                idx = len(flat) - 1
            elif len(k) == 1 and k.lower() in keys:
                idx = keys.index(k.lower())
                _redraw(out, n, render_panel(title, groups, idx, extra))
                break
            else:
                continue
            _redraw(out, n, render_panel(title, groups, idx, extra))
    finally:
        out.write("\x1b[?25h")
        out.flush()
    return flat[idx][0]


def choose(items, default=None, title=None, extra=None):
    return select_menu(title, [items], default, extra)


def stars_row(states, label=""):
    """Wanted-level stars: lit gold for what is ready, dim for what is not."""
    segs = [(" ",)]
    for st in states:
        segs.append(((T.s["star"] if st else T.s["star0"]) + " ", GOLD if st else DIMSTAR, None, True))
    segs.append(("  " + label, LAVENDER))
    return prow(*segs)


def bar_row(filled, total, label=""):
    filled = max(0, min(total, filled))
    return prow((" ",), (T.s["full"] * filled, FRAME), (T.s["empty"] * (total - filled), DIMSTAR), ("  " + label, LAVENDER))


def plate_row(name, value, width=10):
    return prow((" " + name.ljust(width - 1), 225, PLATE), (" " + T.s["back"] + " ", TEAL, None, True),
                (tail(value, panel_inner() - width - 4), CREAM))


# -------------------------------------------------------------------------------------------------------- settings

def load():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(st):
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(SETTINGS, "w", encoding="utf-8", newline="\n") as f:
            json.dump(st, f, indent=2)
    except OSError:
        pass


# ------------------------------------------------------------------------------------------------- environment

def fresh_env():
    """The environment a newly opened terminal would have, so a tool installed a minute ago is found."""
    env = dict(os.environ)
    if os.name != "nt":
        return env
    try:
        import winreg
        paths = []
        for hive, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                          (winreg.HKEY_CURRENT_USER, "Environment")):
            with winreg.OpenKey(hive, sub) as k:
                i = 0
                while True:
                    try:
                        n, v, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    v = os.path.expandvars(v) if isinstance(v, str) else v
                    if n.upper() == "PATH":
                        paths.append(v)
                    else:
                        env[n] = v
        if paths:
            env["PATH"] = os.pathsep.join(paths + [env.get("PATH", "")])
    except Exception:
        pass
    return env


def apply_env():
    os.environ.update(fresh_env())


def ram_gb(available=False):
    if os.name != "nt":
        return None

    class MS(ctypes.Structure):
        _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(f"f{i}", ctypes.c_ulonglong) for i in range(7)]
    m = MS()
    m.l = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return (m.f1 if available else m.f0) / 2**30


def powershell(cmd):
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=30)
        return r.stdout.strip()
    except Exception:
        return ""


def gpus():
    out = powershell("Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name + ' | driver ' + $_.DriverVersion }")
    return [l.strip() for l in out.splitlines() if l.strip()]


def gpu_classes():
    """[(name, kind)] for the real graphics cards; kind is 'discrete' or 'integrated' (virtual adapters are left out)."""
    out = []
    for g in gpus():
        name = g.split(" | ")[0]
        if re.search(r"virtual|parsec|remote|basic|hyper-v|vmware", name, re.I):
            continue
        if re.search(r"nvidia|geforce|quadro|rtx|gtx|radeon rx|radeon pro|\barc\b", name, re.I):
            out.append((name, "discrete"))
        elif re.search(r"intel|uhd|iris|vega|radeon\(tm\) graphics|radeon graphics", name, re.I):
            out.append((name, "integrated"))
        else:
            out.append((name, "discrete"))
    return out


def suggest_jobs(stages):
    """(jobs, [reasons], gpu_note). Starts from upstream's own default (half the CPU threads), lowers it to what the free
    RAM can carry, and, only when the pipelines stage is chosen, to what a GPU driver's shader compiler can take: upstream's
    docs say each large shader needs several GB of RAM there, and its full-corpus run used 4 jobs (docs/design.md)."""
    cpus = os.cpu_count() or 2
    n, why = max(1, cpus // 2), ["%d CPU threads / 2 (upstream's default)" % cpus]
    free = ram_gb(available=True)
    if free:
        cap = max(1, int(free * 0.7 / MEM_PER_JOB_GB))
        if cap < n:
            n = cap
            why.append("%.0f GB of RAM is free: about %d jobs at ~%d GB each (an estimate)" % (free, cap, MEM_PER_JOB_GB))
    cards = gpu_classes()
    names = ", ".join(nm for nm, _ in cards) or "no graphics card found"
    if "pipelines" in stages.split(","):
        cap = 4 if any(k == "discrete" for _, k in cards) else 2
        if cap < n:
            n = cap
        why.append("pipelines: %s compiles on your CPU and RAM, several GB per large shader, so at most %d%s" % (
            names, cap, " (upstream's full run used 4)" if cap == 4 else " (precaution: no discrete GPU found)"))
        note_gpu = "Your GPU: " + names + ". The pipelines stage compiles for it, so it limits the number."
    else:
        note_gpu = "Your GPU: " + names + ". These stages don't use it, so the number comes from CPU threads and free RAM. Add the pipelines stage for a GPU-based limit."
    return n, why, note_gpu


def jobs_for(st, stages):
    return int(st.get("jobs") or suggest_jobs(stages)[0])


def step_jobs(st, stages):
    n, why, note_gpu = suggest_jobs(stages)
    p()
    line("info", "Suggested parallel jobs: %d" % n)
    for w in why:
        note("• " + w if T.uni else "* " + w)
    note(note_gpu)
    note("More jobs is faster until the RAM runs out. Enter takes the suggestion.")
    while True:
        ans = ask("Parallel jobs", st.get("jobs") or n)
        if str(ans).isdigit() and 1 <= int(ans) <= 4 * (os.cpu_count() or 8):
            if int(ans) == n:
                st.pop("jobs", None)
            else:
                st["jobs"] = int(ans)
            return
        p("   " + paint("Type a whole number.", GOLD))


def cpu_name():
    return powershell("(Get-CimInstance Win32_Processor | Select-Object -First 1).Name") or platform.processor()


def free_gb(path):
    d = os.path.abspath(path)
    while d and not os.path.exists(d):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    try:
        return shutil.disk_usage(d).free / 2**30
    except OSError:
        return None


def drives():
    """[(root, free_gb, total_gb, kind)] for fixed, removable and network drives."""
    out = []
    if os.name != "nt":
        return [(os.path.expanduser("~"), free_gb("~") or 0, 0, "fixed")]
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if mask & (1 << i):
            root = chr(65 + i) + ":\\"
            kind = {2: "removable", 3: "fixed", 4: "network"}.get(ctypes.windll.kernel32.GetDriveTypeW(root))
            if kind:
                try:
                    u = shutil.disk_usage(root)
                    out.append((root, u.free / 2**30, u.total / 2**30, kind))
                except OSError:
                    pass
    return out


def has_vulkan_loader():
    return os.name != "nt" or os.path.isfile(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "vulkan-1.dll"))


def tools():
    """[(key, label, present, stage that needs it, how to get it)]"""
    mc = mg.mc_command()[0]
    return [
        ("python", "Python 3.12+", sys.version_info >= (3, 12), "all", platform.python_version()),
        ("git", "git + rpf9-explorer", bool(shutil.which("git")) and mg.submodule_ready(), "assets", "git submodule update --init"),
        ("dotnet", ".NET 8 SDK", mg.dotnet_sdk_ok(), "assets", "winget"),
        ("vulkan", "Vulkan SDK (spirv-as/val)", bool(shutil.which("spirv-as") and shutil.which("spirv-val")), "shaders", "winget"),
        ("llvmmc", "llvm-mc with AMDGPU", bool(os.path.isfile(mc) or shutil.which(mc)), "shaders", "built from source, 20-40 min"),
        ("vs", "Visual Studio C++ tools", mg.visual_cpp_tools_ok() if os.name == "nt" else True, "runtime", "winget"),
        ("ffmpeg", "ffmpeg (optional)", bool(shutil.which("ffmpeg")), "wav", "winget"),
    ]


def needed(stages, wav=False):
    s = set(stages.split(",")) | {"all"} | ({"wav"} if wav else set())
    return [t for t in tools() if t[3] in s]


def pc_rows(install_dir=None):
    rows = []
    ok_os = os.name == "nt" and platform.machine().endswith("64")
    rows.append(("ok" if ok_os else "warn", "System", "%s %s %s" % (platform.system(), platform.release(), platform.machine())))
    rows.append(("ok", "Processor", "%s (%d threads)" % (cpu_name(), os.cpu_count() or 0)))
    r = ram_gb()
    if r is not None:
        rows.append(("ok" if r >= MIN_RAM_GB else "warn", "Memory", "%.0f GB" % r + ("" if r >= MIN_RAM_GB else " (%d+ suggested)" % MIN_RAM_GB)))
    cards = gpus() if os.name == "nt" else []
    for card in cards or ["not detected"]:
        virtual = bool(re.search(r"virtual|parsec|remote|basic", card, re.I))
        rows.append(("info" if virtual or card == "not detected" else "ok", "Graphics", card))
    rows.append(("ok" if has_vulkan_loader() else "bad", "Vulkan", "driver found" if has_vulkan_loader() else "vulkan-1.dll missing: update your GPU driver"))
    if any(re.search(r"nvidia|intel", x, re.I) and not re.search(r"virtual|parsec", x, re.I) for x in cards):
        rows.append(("info", "Shaders", "32-wide GPU: wave64 emulation is chosen automatically"))
    return rows


def show_pc(install_dir=None):
    for state, label, detail in pc_rows(install_dir):
        line(state, label.ljust(10), detail)


def show_drives(need=0):
    for root, free, total, kind in drives():
        state = "ok" if free >= need else "warn"
        line(state, root.ljust(5), "%.0f GB free of %.0f GB (%s)" % (free, total, kind) + ("" if free >= need or not need else "  - not enough for %d GB" % need))


# --------------------------------------------------------------------------------------------- finding the game
# Every copy of this dump is the same package: the same file names and sizes, with MicrosoftGame.Config and the .rpf
# archives in one folder. So the menu looks for that folder by its signature, wherever it is, and says plainly what is
# wrong when a folder is close but not right. Only names and a few file sizes are read.

SKIP = {"windows", "program files", "program files (x86)", "programdata", "appdata", "$recycle.bin", "system volume information",
        "node_modules", ".git", "windowsapps", "recovery", "msocache", "perflogs", "$windows.~bt", "config.msi"}
NAME_HINT = re.compile(r"gta|leonida|dump|xbox|scarlett|rockstar|vi\b|6", re.I)


def looks_like_dump(entries):
    names = {e.name.lower() for e in entries if e.is_file(follow_symlinks=False)}
    return "microsoftgame.config" in names or ("game_scarlett_master.exe" in names and any(n.endswith(".rpf") for n in names))


def describe(folder):
    """(version or None, why not): a plain sentence for a folder that has the package's look but is not a supported copy."""
    v = mg.match_version(folder)
    if v:
        return v, ""
    try:
        v0 = mg.versions()[0]
    except (OSError, IndexError):
        return None, "No version manifest was found in the game folder of this program."
    probs = mg.probe_mismatches(folder, v0)
    return None, "It has the package's look, but it is not a complete %s %s: %s" % (v0["title"], v0["version"], " ".join(probs[:3]))


def deep_scan(roots, budget=90.0, depth=5, show=True):
    """Breadth-first search below roots for folders that look like the package. [(folder, version, why_not)]"""
    found, seen_dirs, t0, last = [], 0, time.time(), 0.0
    queue = collections.deque((r, 0) for r in roots)
    visited = set()
    try:
        while queue and time.time() - t0 < budget:
            d, lvl = queue.popleft()
            try:
                key = os.path.normcase(os.path.realpath(d))
            except OSError:
                continue
            if key in visited:
                continue
            visited.add(key)
            try:
                with os.scandir(d) as it:
                    entries = list(it)
            except OSError:
                continue
            seen_dirs += 1
            if show and T.tty and time.time() - last > 0.2:
                last = time.time()
                sys.stdout.write("\r\x1b[2K   " + paint("Searching %d folders...  " % seen_dirs, 245) + paint(tail(d, T.width() - 30), LAVENDER))
                sys.stdout.flush()
            if looks_like_dump(entries):
                v, why = describe(d)
                found.append((d, v, why))
                continue
            if lvl < depth:
                subs = [e for e in entries if e.is_dir(follow_symlinks=False) and e.name.lower() not in SKIP and not e.name.startswith((".", "$"))]
                subs.sort(key=lambda e: 0 if NAME_HINT.search(e.name) else 1)
                queue.extend((e.path, lvl + 1) for e in subs)
    except KeyboardInterrupt:
        pass
    if show and T.tty:
        sys.stdout.write("\r\x1b[2K")
    return found


def fast_find():
    """The usual places, two levels down (upstream's finder)."""
    try:
        return [(d, v, "") for d, v in mg.find_dumps()]
    except Exception:
        return []


def search_pc():
    roots = [r for r, _, _, k in drives() if k != "network"] if os.name == "nt" else [os.path.expanduser("~")]
    p("   " + paint("Searching every drive for the game package. Press Ctrl+C to stop early.", 245))
    return deep_scan(roots)


def containers_note(folder):
    try:
        return " ".join(mg.container_message(path, h) for path, h in mg.containers_in(folder))
    except Exception:
        return ""


def resolve(path):
    """Turn whatever was typed or dropped into the package folder. (folder or None, message)."""
    path = os.path.expandvars(os.path.expanduser(path.strip().strip('"').strip("'")))
    if not path:
        return None, "Nothing was typed."
    if os.path.isfile(path):
        h = mg.xvd_header(path)
        if h:
            return None, mg.container_message(path, h)
        path = os.path.dirname(path)   # a file inside the package: use its folder
    if not os.path.isdir(path):
        return None, "I can't find that. Check the spelling, or drag the folder onto this window."
    path = os.path.normpath(path)
    v, why = describe(path)
    if v:
        return path, ""
    # a parent of the package, or a subfolder of it (data, pack): look below, then above
    below = [f for f in deep_scan([path], budget=30, depth=3, show=False)]
    good = [f for f in below if f[1]]
    if good:
        return good[0][0], "Found the package inside that folder: " + good[0][0]
    here = os.path.dirname(path)
    for _ in range(2):
        if here and here != os.path.dirname(here):
            vv, _w = describe(here)
            if vv:
                return here, "That was a folder inside the package; using its parent: " + here
            here = os.path.dirname(here)
    if below:
        return None, below[0][2]
    note_c = containers_note(path)
    return None, ("No MicrosoftGame.Config was found in that folder or in the ones below it, so it is not the game package. "
                  "Choose the folder that holds MicrosoftGame.Config and the .rpf files. " + note_c).strip()


def browse():
    """A folder window (Windows' own, through Tk). '' when cancelled or unavailable."""
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return os.path.normpath(filedialog.askdirectory(parent=root, mustexist=True, title="Choose the folder that holds MicrosoftGame.Config") or "")
        finally:
            root.destroy()
    except Exception:
        note("The folder window could not open; type or drag the path instead.")
        return ""


def gb_text(n):
    return "%.1f GB" % (n / 2**30)


def folder_size_hint(folder):
    try:
        return gb_text(sum(e.stat().st_size for e in os.scandir(folder) if e.is_file()))
    except OSError:
        return ""


def step_game(st, n=1, total=4):
    """Returns the package folder, or None if the user went back."""
    heading("Your game copy", (n, total))
    note("Leonida builds from YOUR copy of the Xbox Series package, version 1.0.2.1. It only reads it and never changes it. "
         "Every copy of this package looks alike, so the menu can recognise it by itself.")
    p()
    saved = st.get("game")
    if saved and os.path.isdir(saved) and mg.match_version(saved):
        line("ok", "Last time you used", saved)
        if yesno("Use it again", True):
            return saved
        p()
    p("   " + paint("Looking in the usual places...", 245))
    found = [f for f in fast_find() if f[0] != saved]
    searched = False
    while True:
        items = []
        for i, (d, v, _) in enumerate(f for f in found if f[1]):
            items.append((str(i + 1), os.path.basename(d.rstrip("\\/")) or d, "%s %s   in %s" % (v["title"], v["version"], os.path.dirname(d))))
        good = [f for f in found if f[1]]
        items += [("s", "Search every drive", "looks for the package's signature, up to 5 folders deep"),
                  ("w", "Browse with a folder window", "pick the folder in Windows"),
                  ("t", "Type or drag a folder here", "any folder works: I look inside and above it"),
                  ("b", "Back to the menu", "")]
        for d, v, why in found:
            if not v and why:
                line("warn", d, why)
        title = "Please select your game copy." if good else "I did not find your game copy yet."
        p()
        pick = choose(items, "1" if good else ("t" if searched else "s"), title)
        if pick == "b":
            return None
        if pick == "s":
            found = search_pc()
            searched = True
            if not [f for f in found if f[1]]:
                line("warn", "No supported copy found on your drives.", "choose the folder yourself, or check the copy is complete")
            continue
        if pick in ("w", "t"):
            if pick == "w":
                path = browse()
            else:
                path = ask("Folder (or b to go back)", path=True)
                if path.lower() == "b":
                    continue
            if not path:
                continue
            folder, msg = resolve(path)
            if folder:
                if msg:
                    line("ok", msg)
                return folder
            p("   " + paint(msg, GOLD))
            continue
        return good[int(pick) - 1][0]


# ------------------------------------------------------------------------------------------------ folders and tools

def pick_drive_folder(label, default, need_gb, why):
    """Ask for a folder, showing every drive's free space and warning when the drive is too small."""
    p()
    note(why)
    show_drives(need_gb)
    p()
    while True:
        folder = ask(label + " (Enter keeps this one)", default, path=True)
        folder = os.path.abspath(os.path.expandvars(os.path.expanduser(folder)))
        free = free_gb(folder)
        if need_gb and free is not None and free < need_gb:
            line("warn", "Only %.0f GB free on that drive; about %d GB is needed." % (free, need_gb))
            if not yesno("Use it anyway", False):
                continue
        elif free is not None:
            line("ok", "%.0f GB free there" % free)
        return folder


def best_drive_folder(need_gb, name="Leonida"):
    """A suggestion on the drive with the most free room (when the default has too little)."""
    ds = [d for d in drives() if d[3] != "network"]
    if not ds:
        return None
    root = max(ds, key=lambda d: d[1])
    return os.path.join(root[0], name) if root[1] >= need_gb else None


def step_folders(st, need):
    """Asks where the finished port and the work files go, and saves both."""
    out = pick_drive_folder("Output folder", st.get("out") or DOCS_OUT, 5,
                            "The finished port goes here (derived from your copy; never share it).")
    work_default = st.get("work") or os.path.join(out, "work")
    if (free_gb(work_default) or 0) < need:
        alt = best_drive_folder(need, "Leonida-work")
        if alt:
            line("info", "Suggested work folder: " + alt, "the drive with the most free space")
            work_default = alt
    work = pick_drive_folder("Work folder", work_default, need, "Big temporary files go here (about %d GB for this choice). It can be on another drive." % need)
    st.update(out=out, work=work)
    save(st)


def step_build(st, n=2, total=4, preset=None):
    heading("What to build and where", (n, total))
    items = [(k, label, hint + ("  (~%d GB)" % need if need else "")) for k, (_, label, hint, need) in PRESETS.items()]
    cur = st.get("preset", "1")
    if preset:   # a shortcut from the home menu: no question, and the saved preset stays as it was
        k = preset
        line("info", "Building: " + PRESETS[k][1], PRESETS[k][2])
    else:
        k = choose(items, cur, "What would you like to build?")
        st["preset"] = k
    stages, _, _, need = PRESETS[k]
    if stages == "check":
        return stages, False
    step_folders(st, need)
    wav = "assets" in stages and yesno("Also decode audio to WAV (much larger, needs ffmpeg)", False)
    st["wav"] = wav
    step_jobs(st, stages)
    save(st)
    return stages, wav


def show_requirements(stages, wav=False):
    ts = needed(stages, wav)
    p()
    for l in render_panel("Requirements", [], -1, [stars_row([t[2] for t in ts], "%d of %d ready" % (sum(1 for t in ts if t[2]), len(ts)))]):
        p(l)
    p()
    for key, label, ok, stage, how in ts:
        line("ok" if ok else ("warn" if key == "ffmpeg" else "bad"), label.ljust(28), "found" if ok else "missing  %s  %s" % (T.s["arrow"], how))
    return ts


VSWHERE = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Microsoft Visual Studio", "Installer", "vswhere.exe")
VS_SETUP = os.path.join(os.path.dirname(VSWHERE), "setup.exe")


def vc_tools_path():
    """The Visual Studio folder with the C++ x64 tools, found the way scripts\\build_llvm_mc.ps1 finds it ('' if none)."""
    if not os.path.isfile(VSWHERE):
        return ""
    try:
        r = subprocess.run([VSWHERE, "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                            "-property", "installationPath"], capture_output=True, text=True, timeout=30)
        return r.stdout.strip()
    except Exception:
        return ""


def vs_instances_2022():
    """Complete Visual Studio 2022 installs (a half-finished or cancelled one is skipped), healthiest choice first."""
    if not os.path.isfile(VSWHERE):
        return []
    try:
        r = subprocess.run([VSWHERE, "-all", "-products", "*", "-format", "json"], capture_output=True, text=True, timeout=30)
        data = json.loads(r.stdout or "[]")
    except Exception:
        return []
    ok = [i for i in data if str(i.get("installationVersion", "")).startswith("17.") and i.get("isComplete") and i.get("isLaunchable")]
    return [i["installationPath"] for i in ok]


def add_cpp_to_existing_vs():
    """Add the C++ workload to a complete VS 2022 already on this PC. winget refuses a second install when one is registered
    (even a half-finished one), and this keeps a single Visual Studio. Asks Windows for administrator rights. True if it ran."""
    inst = vs_instances_2022()
    if not inst or not os.path.isfile(VS_SETUP):
        return False
    p()
    p("   " + paint("Adding the C++ tools to your existing Visual Studio:", None, None, True))
    p("   " + paint(inst[0], 245))
    note("A Windows administrator prompt will appear. The installer downloads a few GB; this can take 10-20 minutes.")
    if not yesno("Add the C++ workload there now", True):
        return False
    # Community/Professional name the C++ workload NativeDesktop; VCTools exists only in Build Tools ("Cannot find package" otherwise).
    # The x64 tools and a Windows 11 SDK are named too, because the runtime stage needs both.
    args = ('modify --installPath "%s" --add Microsoft.VisualStudio.Workload.NativeDesktop --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 '
            '--add Microsoft.VisualStudio.Component.Windows11SDK.26100 --includeRecommended --passive --norestart' % inst[0])
    subprocess.call(["powershell", "-NoProfile", "-Command",
                     "Start-Process -FilePath '%s' -ArgumentList '%s' -Verb RunAs -Wait" % (VS_SETUP, args.replace("'", "''"))])
    return True


def run_install(key):
    if key == "vs" and add_cpp_to_existing_vs():
        apply_env()
        return
    label, args, _, _, _ = WINGET[key]
    p()
    p("   " + paint("winget install " + " ".join(args), 245))
    rc = subprocess.call(["winget", "install", *args, "--accept-package-agreements", "--accept-source-agreements"], env=fresh_env())
    if rc:
        line("bad", "%s did not install (exit code %s)." % (label, rc), "scroll up for winget's message")
    apply_env()


def step_tools(st, stages, wav, n=3, total=4):
    """The one place downloads are agreed to. True when everything the stages need is in place."""
    heading("What the build needs", (n, total))
    p("   " + paint("Checking this PC...", 245))
    p()
    show_pc(st.get("out"))
    ts = show_requirements(stages, wav)
    missing = [t for t in ts if not t[2]]
    p()
    if not missing:
        line("ok", "Nothing to install.")
        return True
    hasw = bool(shutil.which("winget"))
    todo = [t for t in missing if t[0] in WINGET and hasw] + [t for t in missing if t[0] in ("llvmmc", "git")]
    if not hasw and any(t[0] in WINGET for t in missing):
        line("warn", "winget was not found.", "install the missing tools by hand (README.md lists them)")
    req = [t for t in todo if t[0] != "ffmpeg"]
    if todo:
        p("   Leonida can set these up. " + paint("Nothing is installed until you say yes.", None, True))
        p()
        pick = choose([("1", "Install what the build needs", "%d item%s" % (len(req), "" if len(req) == 1 else "s")),
                       ("2", "Let me choose one by one", "I'll show each first"),
                       ("3", "Install nothing", "I'll add them myself")], "1" if req else "2")
        for t in todo:
            key = t[0]
            yes = (pick == "1" and t in req) or (pick == "2" and ask_item(t))
            if not yes:
                continue
            if key in WINGET:
                run_install(key)
            elif key == "llvmmc":
                if not vc_tools_path():
                    line("warn", "Skipping llvm-mc for now.", "it needs the Visual Studio C++ tools first; run Start again once they are in")
                    continue
                subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 os.path.join(ROOT, "scripts", "build_llvm_mc.ps1")], env=fresh_env())
                apply_env()
            elif key == "git":
                subprocess.call(["git", "-C", ROOT, "submodule", "update", "--init", "--recursive"])
    ts = show_requirements(stages, wav) if todo else ts
    still = [t for t in ts if not t[2] and t[0] != "ffmpeg"]
    if still:
        p()
        line("bad", "Still missing: " + ", ".join(t[1] for t in still))
        note("If you just installed them, close this window and open Leonida.bat again so Windows refreshes its PATH.")
        return False
    return True


def ask_item(t):
    key = t[0]
    p()
    if key in WINGET:
        label, args, _, source, what = WINGET[key]
        p("   " + paint(label, None, True) + paint("   from " + source, 245))
        note(what + ". Runs: winget install " + " ".join(args[:2]))
    elif key == "llvmmc":
        p("   " + paint("llvm-mc with AMDGPU", None, True) + paint("   built from LLVM sources via scripts\\build_llvm_mc.ps1", 245))
        note("Fetches LLVM sources with git and builds one tool; about 2 GB of temporary space, 20-40 minutes. Needs Visual Studio C++ tools first.")
    else:
        p("   " + paint("rpf9-explorer submodule", None, True) + paint("   git submodule update --init", 245))
    return yesno("Install it", t[0] != "ffmpeg")


# ----------------------------------------------------------------------------------------------- screens

LEGAL_VERSION = "2026-11-24"
LEGAL_POINTS = (
    "You must own the game and supply your own copy of the Xbox Series package. Leonida contains no game files, keys or executable "
    "and downloads none.",
    "Never share your game files, extracted assets or generated shaders, or attach them to issues. They are derived from copyrighted "
    "material and are for your own use on your own PC.",
    "This is an unofficial fan project, not made, approved or sponsored by Rockstar Games or Take-Two. Names and trademarks belong to "
    "their owners.",
    "Laws on copying games differ by country; following yours is your responsibility. This is not legal advice.",
    "Everything is provided as is, with no warranty, under the GPL-3.0. Upstream status: early, the game does not boot yet.")


def legal_gate(st):
    if st.get("legal_ack") == LEGAL_VERSION:
        return True
    heading("Before you start")
    rows = []
    for point in LEGAL_POINTS:
        for i, l in enumerate(wrap(point, panel_inner() - 4)):
            rows.append(prow((" " + (T.s["dot"] if i == 0 else " ") + " " + l, CREAM)))
        rows.append(prow())
    for l in render_panel("Please read this first", [], -1, rows):
        p(l)
    p()
    if not yesno("I own a legal copy of this game and I agree to these terms", False):
        p("   " + paint("No problem. Nothing was started.", 245))
        return False
    st["legal_ack"] = LEGAL_VERSION
    save(st)
    return True


def summary_rows(st, stages, wav):
    ts = needed(stages, wav)
    jobs = jobs_for(st, stages)
    return [plate_row("Game", os.path.basename((st.get("game") or "").rstrip("\\/"))), plate_row("Build", stages),
            plate_row("Output", st.get("out") or "-"), plate_row("Work", st.get("work") or "-"), prow(),
            bar_row(jobs, max(jobs, os.cpu_count() or jobs), "%d jobs at once" % jobs),
            stars_row([t[2] for t in ts], "requirements ready")]


def build_command(st, stages, wav):
    cmd = [sys.executable, "-I", os.path.join(ROOT, "make_game.py"), "--game", st["game"], "--stages", stages]
    if st.get("out") and stages != "check":   # a work folder never chosen is <output>\work, as make_game.py's own default
        cmd += ["--out", st["out"], "--work", st.get("work") or os.path.join(st["out"], "work")]
    cmd += ["--jobs", str(jobs_for(st, stages))]
    if "runtime" in stages.split(",") and st.get("sdl3"):
        cmd += ["--fetch-sdl3"]
    return cmd + (["--wav"] if wav else [])


def step_sdl3(st, stages):
    """Asks once whether the runtime may be built with controller support (SDL3, downloaded by CMake)."""
    if os.name != "nt" or "runtime" not in stages.split(",") or "sdl3" in st:
        return
    heading("Controller support")
    note("The title waits on its sign-in screen until a button is pressed. The runtime reads controllers (and the "
         "keyboard pad) through SDL3, which the build downloads once: the pinned SDL 3.4.20 source from GitHub "
         "(libsdl-org), about 10 MB, checked against its hash. Without it nothing gets past the first screen.")
    st["sdl3"] = yesno("Build the runtime with controller support (downloads SDL3 source)", True)
    save(st)


def result_screen(st, code, log_path):
    p()
    if code == 0:
        box([c("Finished.", GREEN, True), "", "Output:  " + (st.get("out") or ""),
             paint("Upstream status is early: the game does not boot yet. What you built is the toolchain output.", 245)], "All done", GREEN)
        if st.get("out") and os.path.isdir(st["out"]) and yesno("Open the output folder", False):
            try:
                os.startfile(st["out"])
            except (OSError, AttributeError):
                pass
    elif code == 130:
        box([c("Stopped.", GOLD, True), "Nothing is broken. Choose Start again and finished steps are skipped."], "Paused", GOLD)
    else:
        box([c("The build stopped.", RED, True), "", "Read the message above it. The full log is at:", log_path], "Stopped", RED)
    pause()


CMAKE_CONFIG_FILES = ("CMakeCache.txt", "build.ninja", "cmake_install.cmake", "CTestTestfile.cmake")


def stale_cmake_cache():
    """The runtime build folder, if its CMake cache was made for another checkout location.

    CMake refuses to reuse a cache after the project folder is moved or renamed. Returns
    (build_dir, old_source_dir), or None when there is nothing wrong.
    """
    build = os.path.join(ROOT, "runtime", "build")
    try:
        with open(os.path.join(build, "CMakeCache.txt"), encoding="utf-8", errors="replace") as f:
            for ln in f:
                if ln.startswith("CMAKE_HOME_DIRECTORY:"):
                    old = ln.split("=", 1)[1].strip()
                    here = os.path.join(ROOT, "runtime")
                    same = os.path.normcase(os.path.normpath(old)) == os.path.normcase(os.path.normpath(here))
                    return None if same else (build, old)
    except OSError:
        pass
    return None


def fix_stale_cmake_cache(stages):
    """Offer to clear the CMake settings left behind by a moved folder (compiled output is kept)."""
    if "runtime" not in stages:
        return
    stale = stale_cmake_cache()
    if not stale:
        return
    build, old = stale
    line("warn", "The runtime build folder was set up for a different location.")
    note("It points at: " + old)
    note("CMake would stop with 'CMakeCache.txt is different than the directory where it was created'.")
    note("Clearing only its saved settings (not the compiled files) lets CMake set it up again here.")
    if not yesno("Clear the old CMake settings in runtime\\build", True):
        note("Left as is. The runtime stage will probably fail until this is cleared.")
        return
    for name in CMAKE_CONFIG_FILES:
        try:
            os.remove(os.path.join(build, name))
        except OSError:
            pass
    shutil.rmtree(os.path.join(build, "CMakeFiles"), ignore_errors=True)
    line("ok", "Cleared. CMake will configure it again; some files may be rebuilt.")


def do_build(st, stages, wav):
    os.makedirs(LOG_DIR, exist_ok=True)
    for old in sorted(os.listdir(LOG_DIR))[:-9]:
        try:
            os.remove(os.path.join(LOG_DIR, old))
        except OSError:
            pass
    log_path = os.path.join(LOG_DIR, time.strftime("build-%Y%m%d-%H%M%S.log"))
    cmd = build_command(st, stages, wav)
    with open(log_path, "w", encoding="utf-8") as lf:
        lf.write(subprocess.list2cmdline(cmd) + "\n")
    note("Building. Ctrl+C stops it safely; starting again carries on where it can.")
    try:
        code = subprocess.call(cmd, env=fresh_env())
    except KeyboardInterrupt:
        code = 130
    with open(log_path, "a", encoding="utf-8") as lf:
        lf.write("exit code %s\n" % code)
    return code, log_path


def install_flow(st, preset=None):
    if not legal_gate(st):
        pause()
        return
    game = step_game(st)
    if not game:
        return
    st["game"] = game
    save(st)
    stages, wav = step_build(st, preset=preset)
    if stages != "check" and not step_tools(st, stages, wav):
        pause()
        return
    step_sdl3(st, stages)
    p()
    if select_menu("Start this build?", [[("y", "Yes", "start building"), ("q", "Quit", "back to the menu")]], "y", summary_rows(st, stages, wav)) != "y":
        return
    fix_stale_cmake_cache(stages)
    code, log_path = do_build(st, stages, wav)
    note_built(st, stages, code)
    result_screen(st, code, log_path)


def note_built(st, stages, code):
    """After a finished build, remembers which commit its shader and runtime steps were built from (for Update)."""
    if code != 0:
        return
    info = bta_update.commit_info(ROOT) if bta_update.is_checkout(ROOT) else None
    if not info:
        return
    built = st.setdefault("built", {})
    for step in ("shaders", "runtime"):
        if step in stages.split(","):
            built[step] = info["hash"]
    save(st)


def screen_update(st):
    heading("Update Banana Theft Auto")
    note("Compares this folder with the Banana Theft Auto repository on GitHub, shows what is new, and updates it. "
         "Only code changes are downloaded (usually a few MB). Nothing changes until you say yes.")
    if not yesno("Check GitHub for updates now", True):
        return
    p("   " + paint("Checking...", 245))
    s = bta_update.scan(ROOT, st.get("built"))
    if s["kind"] == "no-git":
        line("bad", "Updating needs git, which is not installed.",
             "Check this PC > tools offers it, or: winget install --id Git.Git -e")
        note("Or download the latest version as a ZIP from " + bta_update.REPO_PAGE + " (Code > Download ZIP).")
        pause()
        return
    if s["kind"] == "no-checkout":
        line("warn", "This folder was not downloaded with git (probably a ZIP), so it cannot update itself.")
        note("Get the latest ZIP from " + bta_update.REPO_PAGE + ", or clone it once with git so Update works from then on:")
        note("git clone " + bta_update.REPO_URL)
        pause()
        return
    cur, latest = s["current"], s["latest"]
    if cur:
        line("ok", "Your version:   %s  (%s)" % (cur["short"], cur["date"]), shorten(cur["subject"], 50))
    if s["error"]:
        line("warn", "Could not reach GitHub.", shorten(s["error"], 70))
    elif latest:
        line("ok" if not s["behind"] else "warn", "Latest version: %s  (%s)" % (latest["short"], latest["date"]),
             "you are up to date" if not s["behind"] else "%d update(s) available" % s["behind"])
    for step in s["rebuild"]:
        line("warn", "Your built %s is older than this folder's code." % ("shaders" if step == "shaders" else "game runtime"),
             "rebuild it below")
    steps = list(s["rebuild"])
    if s["behind"]:
        heading("What's new")
        for short, date, subject in s["new_commits"][:15]:
            p("   " + paint(short, TEAL) + "  " + paint(date, 245) + "  " + shorten(subject, T.width() - 30))
        if len(s["new_commits"]) > 15:
            p("   " + paint("... and %d more" % (len(s["new_commits"]) - 15), 245))
        p()
        if s["steps"]:
            note("This update changes: " + " and ".join("the shaders (a longer rebuild)" if x == "shaders" else
                                                         "the game runtime (a quick rebuild)" for x in s["steps"]) + ".")
        else:
            note("This update needs no rebuild.")
        if s["ahead"]:
            line("bad", "This folder has %d commit(s) of its own, so it cannot be updated automatically." % s["ahead"])
            pause()
            return
        keep = False
        if s["local"]:
            line("warn", "You have changed %d file(s) here:" % len(s["local"]), ", ".join(s["local"][:4]))
            keep = yesno("Set your changes aside, update, then put them back", True)
            if not keep:
                pause()
                return
        if not yesno("Update now", True):
            return
        ok, msg = bta_update.update(ROOT, keep_local=keep)
        line("ok" if ok else "bad", msg)
        if not ok:
            pause()
            return
        steps = [x for x in ("shaders", "runtime") if x in steps or x in s["steps"]]
        note("The menu itself may have changed: close it and start Leonida.bat again when you are done here.")
    if not steps:
        if not s["behind"]:
            note("Nothing to do.")
        pause()
        return
    if not st.get("game"):
        note("Choose Start to build: no game copy is set yet.")
        pause()
        return
    stages = "check," + ",".join(steps)
    if not st.get("out"):
        # Never fall back to make_game.py's default (Documents, on C:) without asking.
        line("info", "No output folder is saved yet. Choose where the build goes.")
        step_folders(st, 30 if "shaders" in steps else 1)
    note("Building into: " + st["out"] + "   (work files: " + (st.get("work") or os.path.join(st["out"], "work")) + ")")
    if not yesno("Rebuild now (%s)" % " and ".join(steps), True):
        note("You can rebuild later with Start (Runtime only, or Run the port when the shaders changed).")
        pause()
        return
    step_sdl3(st, stages)
    fix_stale_cmake_cache(stages)
    code, log_path = do_build(st, stages, False)
    note_built(st, stages, code)
    result_screen(st, code, log_path)


def screen_buildcheck(st):
    heading("Check my build")
    note("Looks at your build after a power cut, a crash or an update: what is still good, what is out of date, and "
         "what an interrupted run left behind. Nothing is deleted unless you say yes.")
    out, _ = run_folder(st)
    work = st.get("work") or os.path.join(out, "work")
    p("   " + paint("Checking " + out + " and " + work + " ...", 245))
    head = bta_update.commit_info(ROOT)["hash"] if bta_update.is_checkout(ROOT) and bta_update.commit_info(ROOT) else None
    sh, sh_why = bta_buildcheck.shader_state(work, mg)
    rt, rt_why = bta_buildcheck.runtime_state(out, (st.get("built") or {}).get("runtime"), head)
    ca, ca_why = bta_buildcheck.cache_state(out)
    tone = {"current": "ok", "ok": "ok", "missing": "info", "none": "info", "unknown": "info",
            "interrupted": "warn", "outdated": "warn", "broken": "bad"}
    p()
    line(tone[sh], "Shaders: " + sh, sh_why)
    line(tone[rt], "Game runtime: " + rt, rt_why)
    line(tone[ca], "Shader cache: " + ca, ca_why)
    junk = bta_buildcheck.leftovers(out, work)
    junk_bytes = sum(b for _, b, _ in junk)
    if junk:
        line("warn", "%d leftover file(s) from an interrupted run (%s)" % (len(junk), bta_buildcheck.gb(junk_bytes)),
             shorten(junk[0][0], 60))
    else:
        line("ok", "No leftovers from interrupted runs")
    p()
    if sh == "interrupted" or (rt in ("missing",) and sh != "missing"):
        note("Your finished steps are kept. Choose Start and the build carries on from where it stopped.")
    if junk and yesno("Delete the %d leftover file(s) (%s)" % (len(junk), bta_buildcheck.gb(junk_bytes)), True):
        gone = 0
        for path, _, _ in junk:
            try:
                os.remove(path)
                gone += 1
            except OSError:
                pass
        line("ok", "Deleted %d file(s)" % gone)
    if ca == "broken" and yesno("Delete the damaged shader cache (it is rebuilt on the next run)", True):
        try:
            os.remove(os.path.join(out, "pipeline_cache.bin"))
            line("ok", "Deleted; the next run builds it again")
        except OSError as e:
            line("bad", "Could not delete it", str(e))
    old = bta_buildcheck.obsolete_translation(work, mg)
    if old:
        path, size = old
        note("The translated shaders are from an older version and will be made again on the next Start anyway. "
             "Deleting them now frees the space early; the slow unpacking and disassembly are kept.")
        if yesno("Delete the out-of-date translated shaders (%s)" % bta_buildcheck.gb(size), False):
            shutil.rmtree(path, ignore_errors=True)
            line("ok", "Deleted " + path)
    if rt == "outdated" or sh == "outdated":
        note("To bring it up to date: choose Update (it rebuilds only what changed), or Start.")
    pause()


def run_folder(st):
    """The built port folder (gta6rt.exe and game_path.txt) and where run logs go."""
    out = st.get("out") or DOCS_OUT
    work = st.get("work") or os.path.join(out, "work")
    return out, os.path.join(work, "runlogs")


def screen_run(st):
    heading("Run the game")
    out, logs = run_folder(st)
    if not os.path.isfile(os.path.join(out, "gta6rt.exe")) or not os.path.isfile(os.path.join(out, "game_path.txt")):
        line("bad", "No built port in " + out, "choose Start first (Run the port), or set the output folder in Settings")
        pause()
        return
    for text in ("The title's window opens minimised. Restore it from the taskbar (a minimised window is never drawn into).",
                 "Loading takes several minutes. The screen stays black, then grey, until the sign-in screen shows its button prompts.",
                 "Then press A on the controller (Enter on the keyboard pad). The frame rate is very low: press once and wait.",
                 "Next come Legal Notices, Finish setup, Navigation options and the logo splash.",
                 "Plug a controller in before starting. The runtime must be built with controller support (asked at Start)."):
        for i, l in enumerate(wrap(text, T.width() - 8)):
            p("   " + (paint(T.s["dot"], FRAME) + " " if i == 0 else "  ") + l)
    p()
    pad = yesno("Use the keyboard as a pad (arrows = d-pad, Enter = A, Backspace = B, Esc = Menu)", False)
    mins = ask("Stop it after how many minutes", str(st.get("run_minutes", 15)))
    try:
        mins = max(1, int(mins))
    except (TypeError, ValueError):
        mins = 15
    st["run_minutes"] = mins
    save(st)
    env = fresh_env()
    if pad:
        env["LEONIDA_KEYBOARD_PAD"] = "1"
    os.makedirs(logs, exist_ok=True)
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(ROOT, "scripts", "run_logged.ps1"),
           "-Port", out, "-LogRoot", logs, "-Experiments", "-TitleWindow", "-TimeoutSec", str(mins * 60)]
    note("Running. The summary appears here when it ends; closing the game ends it early.")
    try:
        code = subprocess.call(cmd, env=env)
    except KeyboardInterrupt:
        code = 130
    p()
    if code == 0:
        note("Logs: " + logs + " (newest run-... folder). Look for 'gameinput: SDL 3.4.20 gamepads' above.")
        note("Share only summary lines, never game files, captures or shader output.")
    else:
        line("warn", "The run script stopped with code %s." % code, "read the message above it")
    pause()


def screen_check(st):
    heading("Your PC")
    p("   " + paint("Checking...", 245))
    show_pc(st.get("out"))
    heading("Free space")
    show_drives(0)
    p("   " + paint("Upstream estimates: run the port ~30 GB, full build ~400 GB.", 245))
    heading("Tools")
    show_requirements("check,shaders,assets,runtime", False)
    p()
    note("Nothing is installed from this screen. Choose Start and you are asked item by item.")
    pause()


def screen_find(st):
    heading("Find my game copy")
    game = step_game(st, 1, 1)
    if game:
        st["game"] = game
        save(st)
        line("ok", "Using " + game)
        pause()


def screen_downloads():
    heading("What can be installed")
    for key, (label, args, stage, source, what) in WINGET.items():
        p("   " + paint(label, None, True) + paint("   needed for: %s   source: %s" % (stage, source), 245))
        note(what)
    p("   " + paint("llvm-mc with AMDGPU", None, True) + paint("   needed for: shaders   source: LLVM sources, built locally", 245))
    note("Official Windows LLVM lacks it, so scripts\\build_llvm_mc.ps1 builds it (20-40 minutes).")
    p()
    pause()


def settings_screen(st):
    while True:
        heading("Settings")
        p("   Game:     " + (st.get("game") or paint("not chosen yet", 245)))
        p("   Output:   " + (st.get("out") or DOCS_OUT + paint("  (standard)", 245)))
        p("   Work:     " + (st.get("work") or paint("<output>\\work", 245)))
        p("   Jobs:     " + (str(st.get("jobs")) + paint("  (your choice)", 245) if st.get("jobs") else paint("suggested from your PC each time", 245)))
        p()
        k = choose([("1", "Change the game copy", ""), ("2", "Change the output folder", ""), ("3", "Change the work folder", ""),
                    ("4", "Change the job count", "parallel work"), ("b", "Back", "")], "b")
        if k == "1":
            g = step_game(st, 1, 1)
            if g:
                st["game"] = g
        elif k == "2":
            st["out"] = pick_drive_folder("Output folder", st.get("out") or DOCS_OUT, 5, "The finished port goes here.")
        elif k == "3":
            st["work"] = pick_drive_folder("Work folder", st.get("work") or DOCS_OUT, 30, "Big temporary files go here (30 GB, or 400 GB for a full build).")
        elif k == "4":
            step_jobs(st, PRESETS.get(st.get("preset", "1"), PRESETS["1"])[0])
        else:
            return
        save(st)


def help_screen():
    heading("Help")
    for text in ("Start walks you through it: your game copy, what to build and where, then what to install. Nothing is installed until you say yes.",
                 "Find my game copy recognises the package by its files, so it works wherever the copy is, even in a folder you point at by mistake.",
                 "Stopping is safe. Press Ctrl+C during a build; finished steps are skipped when you start again.",
                 "Run the game starts the built port with logging. Restore its window, wait for the button prompts, press A.",
                 "Update checks GitHub for a newer version, updates this folder (keeping your own edits) and rebuilds only what changed.",
                 "After pulling new code, Start with Runtime only rebuilds gta6rt.exe without redoing the shaders.",
                 "Logs are in " + LOG_DIR + ". Your choices are in " + SETTINGS + " (paths and numbers only).",
                 "The same build runs from a script: py -I make_game.py --game <folder> --stages check,shaders,runtime (see --help).",
                 "Never share your game files or anything built from them."):
        for i, l in enumerate(wrap(text, T.width() - 8)):
            p("   " + (paint(T.s["dot"], FRAME) + " " if i == 0 else "  ") + l)
        p()
    pause()


HOME = [[("1", "Start", "your game, then build"), ("s", "Shaders only", "run just the shader step"),
         ("r", "Run the game", "start the built port and log it")],
        [("u", "Update", "get the latest version from GitHub"), ("c", "Check my build", "after a power cut, crash or update"),
         ("2", "Check this PC", "hardware, drives, tools"),
         ("3", "Find my game copy", "I look for it for you")],
        [("4", "What can be installed", "every tool and its source"), ("5", "Settings", "folders and speed"), ("6", "Help", "")],
        [("q", "Quit", "")]]


def home():
    st = load()
    while True:
        if T.tty and T.color:
            sys.stdout.write("\x1b[2J\x1b[H")
        banner()
        if st.get("game") and shutil.get_terminal_size((90, 40)).lines >= 34:
            p("   " + paint("Game: ", 245) + tail(st["game"], T.width() - 12))
        p()
        k = select_menu("Welcome to Leonida. Please select an option.", HOME, "1")
        try:
            if k == "1":
                install_flow(st)
            elif k == "s":
                install_flow(st, preset="3")
            elif k == "r":
                screen_run(st)
            elif k == "u":
                screen_update(st)
            elif k == "c":
                screen_buildcheck(st)
            elif k == "2":
                screen_check(st)
            elif k == "3":
                screen_find(st)
            elif k == "4":
                screen_downloads()
            elif k == "5":
                settings_screen(st)
            elif k == "6":
                help_screen()
            else:
                raise Quit()
        except KeyboardInterrupt:
            p()
            p("  " + paint("Back at the menu.", 245))


def preview():
    banner()
    p()
    for l in render_panel("Welcome to Leonida. Please select an option.", HOME, 0):
        p(l)
    heading("Your PC")
    show_pc()
    heading("Free space")
    show_drives(30)
    heading("What the build needs")
    show_requirements("check,shaders,assets,runtime", False)
    st = {"game": r"D:\Dumps\GTA6v1.0.2.1", "out": DOCS_OUT, "work": r"D:\Leonida-work", "jobs": 10}
    heading("Start this build?")
    for l in render_panel("Start this build?", [[("y", "Yes", "start building"), ("q", "Quit", "back to the menu")]], 0,
                          summary_rows(st, "check,shaders,runtime", False)):
        p(l)
    p()
    box([c("Finished.", GREEN, True), "", "Output:  " + DOCS_OUT], "All done", GREEN)
    p()
    box([c("The build stopped.", RED, True), "", "Read the message above it."], "Stopped", RED)
    p()


def main():
    init()
    try:
        if "--preview" in sys.argv:
            preview()
        elif "--check" in sys.argv:
            screen_buildcheck(load())
        elif "--update" in sys.argv:
            screen_update(load())
        elif "--pc" in sys.argv:
            screen_check(load())
        elif "--find" in sys.argv:
            for d, v, why in fast_find() + search_pc():
                p("  %s  %s" % (d, ("(%s %s)" % (v["title"], v["version"])) if v else why))
        else:
            home()
    except (Quit, KeyboardInterrupt):
        pass
    p()
    p("  " + paint("Goodbye.", 245))
    p()


if __name__ == "__main__":
    main()
