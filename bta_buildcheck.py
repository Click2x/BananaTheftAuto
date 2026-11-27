# Banana Theft Auto: "Check my build" for the guided menu (leonida_menu.py).
# Standard library only. Reads the output and work folders, says which parts are current, out of date or interrupted,
# and finds leftovers an interrupted run (a power cut, a crash, Ctrl+C) can leave. It deletes nothing by itself: the
# menu asks first, and only files listed by `leftovers()` or `obsolete_translation()` are ever removed.
import os
import struct

TEMP_SUFFIXES = (".tmp", ".partial", ".precompile.tmp", ".staging")
SPIRV_MAGIC = 0x07230203


def folder_bytes(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def gb(n):
    return "%.1f GB" % (n / 1e9) if n >= 1e8 else "%.0f MB" % (n / 1e6)


def _spirv_ok(path):
    try:
        with open(path, "rb") as f:
            head = f.read(20)
    except OSError:
        return False
    return len(head) == 20 and struct.unpack_from("<I", head)[0] == SPIRV_MAGIC


def leftovers(*folders, check_spirv=True, limit=200000):
    """Files an interrupted run leaves: temporary and partial files, and empty or cut-off .spv files.
    Returns [(path, bytes, why)]."""
    found = []
    seen = 0
    for top in folders:
        if not top or not os.path.isdir(top):
            continue
        for root, _dirs, files in os.walk(top):
            for name in files:
                seen += 1
                if seen > limit:
                    return found
                path = os.path.join(root, name)
                low = name.lower()
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                if low.endswith(TEMP_SUFFIXES):
                    found.append((path, size, "temporary file from a run that stopped"))
                elif check_spirv and low.endswith(".spv") and (size == 0 or not _spirv_ok(path)):
                    found.append((path, size, "shader file cut off part-way"))
    return found


def shader_state(work, mg=None):
    """('missing' | 'interrupted' | 'current' | 'outdated', detail) for the translated shaders in <work>/shaders."""
    spirv = os.path.join(work or "", "shaders", "spirv")
    dxbc = os.path.join(work or "", "shaders", "dxbc")
    if not os.path.isdir(spirv) and not os.path.isdir(dxbc):
        return "missing", "no shader work yet"
    if not os.path.isfile(os.path.join(spirv, "index.json")):
        disasm = os.path.isfile(os.path.join(dxbc, "disasm.done"))
        return "interrupted", ("unpacking and disassembly are done; the translation stopped part-way and resumes"
                               if disasm else "the shader step stopped part-way; Start resumes it")
    if mg is not None:
        try:
            have = mg.read_shader_setting(os.path.join(spirv, "translation_sources.sha256"))
            if have != mg.translation_sources_digest():
                return "outdated", ("made by an older translator: the next Start translates them again "
                                    "(the slow unpacking and disassembly are kept)")
        except Exception:
            pass
    return "current", "made by this version's translator"


def obsolete_translation(work, mg=None):
    """The translated shader folder when it is out of date (it is rebuilt anyway), else None: (path, bytes)."""
    state, _ = shader_state(work, mg)
    if state != "outdated":
        return None
    spirv = os.path.join(work, "shaders", "spirv")
    return spirv, folder_bytes(spirv)


def cache_state(out):
    """The Vulkan pipeline cache beside gta6rt.exe: ('none' | 'ok' | 'broken', detail)."""
    path = os.path.join(out or "", "pipeline_cache.bin")
    if not os.path.isfile(path):
        return "none", "no shader cache yet (the first run builds it)"
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(32)
    except OSError:
        return "broken", "unreadable"
    # VkPipelineCacheHeaderVersionOne: u32 header length (32), u32 version (1).
    if size < 32 or len(head) < 32 or struct.unpack_from("<II", head) != (32, 1):
        return "broken", "cut off or damaged: it will be rebuilt (delete it to start clean)"
    return "ok", gb(size)


def runtime_state(out, built, head):
    """gta6rt.exe in <out>: ('missing' | 'current' | 'outdated' | 'unknown', detail). built: the commit its last
    finished build was made from (the menu remembers it), head: this folder's commit."""
    if not os.path.isfile(os.path.join(out or "", "gta6rt.exe")):
        return "missing", "not built yet"
    if not built or not head:
        return "unknown", "built, version not recorded"
    return ("current", "built from this version") if built == head else ("outdated", "built from an older version")
