# Banana Theft Auto: version scanner and updater for the guided menu (leonida_menu.py, "Update").
# Standard library only; uses the git command line.
#
# It compares this folder with the Banana Theft Auto repository on GitHub, lists the new commits, updates with a
# fast-forward only (never a merge or a reset), and says which build steps the update needs. Upstream Leonida changes
# reach users through the Banana Theft Auto repository once they have been reviewed, never directly.
import os
import subprocess

REPO_URL = "https://github.com/Click2x/BananaTheftAuto.git"
REPO_PAGE = "https://github.com/Click2x/BananaTheftAuto"
BRANCH = "main"
TRACK = "refs/remotes/bta-update/main"   # where a check keeps what it fetched; touches no branch

# Paths whose change needs a build step. Anything else (docs, the menu, scripts) works without one. The shader step's
# inputs are make_game.py's own lists, so the two never disagree.
try:
    import make_game as _mg
    SHADER_PATHS = tuple("tools/" + n for n in (*_mg.TRANSLATION_SOURCES, *_mg.FSPX_TOOLS))
except (ImportError, AttributeError):
    SHADER_PATHS = ("tools/rdna2spirv.py", "tools/shader_disasm.py", "tools/rdna2_decode.py",
                    "tools/rdna2_isa_tables.py", "tools/fspx_unpack.py")
RUNTIME_PATHS = ("runtime/",)


def git(root, *args, timeout=120):
    """(exit code, stdout) of one git command in root; (-1, reason) when git cannot run."""
    try:
        r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return -1, "git is not installed"
    except subprocess.TimeoutExpired:
        return -1, "git took too long (is the network down?)"
    return r.returncode, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout)).rstrip()


def is_checkout(root):
    return os.path.isdir(os.path.join(root, ".git")) and git(root, "rev-parse", "--git-dir")[0] == 0


def commit_info(root, ref="HEAD"):
    """{'hash', 'short', 'date', 'subject'} of a commit, or None."""
    code, out = git(root, "log", "-1", "--format=%H%x1f%h%x1f%cs%x1f%s", ref)
    if code != 0 or not out:
        return None
    full, short, date, subject = (out.split("\x1f") + ["", "", "", ""])[:4]
    return {"hash": full, "short": short, "date": date, "subject": subject}


def local_changes(root):
    """Tracked files changed here (untracked files are ignored: an update never touches them)."""
    code, out = git(root, "status", "--porcelain", "--untracked-files=no")
    return [ln[3:] for ln in out.splitlines() if ln.strip()] if code == 0 else []


def build_steps(paths):
    """The build stages a set of changed paths needs: 'shaders' and/or 'runtime', in build order."""
    steps = []
    if any(p.startswith(SHADER_PATHS) for p in paths):
        steps.append("shaders")
    if any(p.startswith(RUNTIME_PATHS) for p in paths):
        steps.append("runtime")
    return steps


def changed_paths(root, old, new):
    code, out = git(root, "diff", "--name-only", old, new)
    return out.splitlines() if code == 0 else None


def fetch(root):
    """Downloads the repository's latest commit list into TRACK. (ok, message)."""
    code, out = git(root, "fetch", "--no-tags", "--quiet", REPO_URL, "+%s:%s" % (BRANCH, TRACK), timeout=300)
    return code == 0, out


def scan(root, built=None, do_fetch=True):
    """What this folder holds compared with GitHub.

    Returns a dict: kind ('checkout' / 'no-git' / 'no-checkout'), current, latest (commit infos), behind, ahead,
    new_commits [(short, date, subject)], local (changed tracked files), branch, steps (build steps the update needs),
    rebuild (build steps whose last build, built = {step: commit hash}, is older than this folder's source), error.
    """
    s = {"kind": "checkout", "current": None, "latest": None, "behind": 0, "ahead": 0, "new_commits": [], "local": [],
         "branch": None, "steps": [], "rebuild": [], "error": None}
    if git(root, "--version")[0] != 0:
        s["kind"] = "no-git"
        return s
    if not is_checkout(root):
        s["kind"] = "no-checkout"
        return s
    s["current"] = commit_info(root)
    code, branch = git(root, "symbolic-ref", "--short", "-q", "HEAD")
    s["branch"] = branch if code == 0 else None
    s["local"] = local_changes(root)
    for step, commit in sorted((built or {}).items()):
        if s["current"] and commit and commit != s["current"]["hash"]:
            paths = changed_paths(root, commit, "HEAD")
            if paths is None or step in build_steps(paths):
                s["rebuild"].append(step)
    s["rebuild"].sort(key=["shaders", "runtime"].index)
    if do_fetch:
        ok, msg = fetch(root)
        if not ok:
            s["error"] = msg or "could not reach GitHub"
            return s
    s["latest"] = commit_info(root, TRACK)
    if not s["latest"]:
        return s
    code, out = git(root, "rev-list", "--left-right", "--count", "HEAD..." + TRACK)
    if code == 0 and out:
        ahead, behind = out.split()
        s["ahead"], s["behind"] = int(ahead), int(behind)
    if s["behind"]:
        code, out = git(root, "log", "--format=%h%x1f%cs%x1f%s", "HEAD.." + TRACK)
        if code == 0:
            s["new_commits"] = [tuple((ln.split("\x1f") + ["", ""])[:3]) for ln in out.splitlines() if ln]
        paths = changed_paths(root, "HEAD", TRACK)
        s["steps"] = build_steps(paths) if paths is not None else ["shaders", "runtime"]
    return s


def update(root, keep_local=False):
    """Fast-forwards this folder to TRACK. (ok, message).

    keep_local: local changes to tracked files are set aside first (git stash) and put back afterwards. Without it,
    an update with local changes is refused. Commits of your own (ahead of GitHub) are never thrown away: the update
    is refused and the folder is left as it is.
    """
    if not commit_info(root, TRACK):
        return False, "Check for updates first."
    code, out = git(root, "rev-list", "--left-right", "--count", "HEAD..." + TRACK)
    if code != 0:
        return False, out
    ahead, behind = (int(x) for x in out.split())
    if not behind:
        return True, "Already up to date."
    if ahead:
        return False, ("This folder has %d commit(s) of its own that GitHub does not have, so it cannot simply be "
                       "moved forward. Nothing was changed." % ahead)
    if git(root, "symbolic-ref", "-q", "HEAD")[0] != 0:
        return False, "This folder is not on a branch (detached HEAD). Nothing was changed."
    stashed = False
    if local_changes(root):
        if not keep_local:
            return False, "You have changed files here. Nothing was changed."
        code, out = git(root, "stash", "push", "-m", "BTA updater: local changes")
        if code != 0:
            return False, "Could not set your changes aside: " + out
        stashed = True
    code, out = git(root, "merge", "--ff-only", "--quiet", TRACK)
    if code != 0:
        if stashed:
            git(root, "stash", "pop")
        return False, "The update could not be applied: " + out
    note = ""
    if os.path.isfile(os.path.join(root, ".gitmodules")):
        git(root, "submodule", "update", "--init", "--recursive", timeout=600)
    if stashed:
        code, out = git(root, "stash", "pop")
        note = (" Your changes were put back." if code == 0 else
                " Your changes clash with the update; they are kept safe in 'git stash list' (BTA updater).")
    return True, "Updated." + note
