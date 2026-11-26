#!/usr/bin/env python3
"""Map which shader programs the title compiles at each part of a run (Banana Theft Auto).

Reads a run log written with LEONIDA_PSO_PROFILE=1 (runtime/src/pipeline_profile.h prints one `pso-driver begin` and one
`pso-driver end` line per pipeline the driver builds) and writes:

  <out>/pso_timeline.csv    one row per pipeline build: seconds since the first build, stage (cs, gfx...), origin (what asked
                            for it: warmup, dispatch, draw...), program, pixel shader, milliseconds, result, phase
  <out>/pso_phases.md       per phase: how many builds, how long they took in all, and the slowest; the programs built on
                            first use (origin dispatch/draw), which stall the title and are the candidates for preloading
  <out>/preload_<phase>.txt the programs first built in that phase, slowest first, one name per line (a preloader's input)

Phases are named with --phase NAME@SECONDS (seconds since the first build; repeatable), e.g.
  --phase boot@0 --phase sign-in@100 --phase setup@140 --phase loading@200
Without --phase the run is cut into fixed windows (--window, default 30 s).

Program names are the translated library's file names (lib_cs_01468, ...), not game data, but the outputs stay in the
work folder like every other run output.
"""
import argparse
import csv
import os
import re
import sys
from collections import defaultdict

BEGIN = re.compile(r"pso-driver begin id=(\d+) unix_ms=(\d+) stage=(\S+) origin=(\S+) program=(\S+) ps=(\S+)")
END = re.compile(r"pso-driver end id=(\d+) unix_ms=(\d+) us=(-?\d+) cpu_us=(-?\d+) result=(-?\d+)")
STALLING = ("dispatch", "draw", "replay", "execute")


def parse(lines):
    """Builds as dicts, in begin order. A begin without an end (the run stopped) has ms None."""
    builds, by_id = [], {}
    for line in lines:
        m = BEGIN.search(line)
        if m:
            b = {"id": int(m[1]), "start_ms": int(m[2]), "stage": m[3], "origin": m[4], "program": m[5], "ps": m[6],
                 "ms": None, "result": None}
            builds.append(b)
            by_id[b["id"]] = b
            continue
        m = END.search(line)
        if m and int(m[1]) in by_id:
            b = by_id[int(m[1])]
            b["ms"] = int(m[3]) / 1000.0
            b["result"] = int(m[5])
    return builds


def phases_from(args_phases, window, last_s):
    if args_phases:
        out = []
        for p in args_phases:
            name, _, at = p.rpartition("@")
            if not name:
                raise SystemExit(f"--phase {p!r}: expected NAME@SECONDS")
            out.append((float(at), name))
        return sorted(out)
    n = int(last_s // window) + 1
    return [(i * window, f"t{int(i * window):04d}-{int((i + 1) * window):04d}s") for i in range(n)]


def phase_of(t, phases):
    name = phases[0][1]
    for at, n in phases:
        if t >= at:
            name = n
    return name


def stalls(b):
    return any(b["origin"].startswith(s) for s in STALLING)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", help="a run's raw.txt (or any file with the pso-driver lines)")
    ap.add_argument("--out", required=True, help="folder for the outputs (keep it in the work folder)")
    ap.add_argument("--phase", action="append", default=[], help="NAME@SECONDS since the first build (repeatable)")
    ap.add_argument("--window", type=float, default=30.0, help="window length without --phase (seconds)")
    a = ap.parse_args(argv)

    with open(a.log, encoding="utf-8", errors="replace") as f:
        builds = parse(f)
    if not builds:
        print("no pso-driver lines: run the title with LEONIDA_PSO_PROFILE=1", file=sys.stderr)
        return 1
    t0 = builds[0]["start_ms"]
    for b in builds:
        b["t"] = (b["start_ms"] - t0) / 1000.0
    phases = phases_from(a.phase, a.window, builds[-1]["t"])
    for b in builds:
        b["phase"] = phase_of(b["t"], phases)

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "pso_timeline.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "stage", "origin", "program", "ps", "ms", "result", "phase"])
        for b in builds:
            w.writerow([f"{b['t']:.3f}", b["stage"], b["origin"], b["program"], b["ps"],
                        "" if b["ms"] is None else f"{b['ms']:.1f}", "" if b["result"] is None else b["result"],
                        b["phase"]])

    seen = set()
    first_in = defaultdict(list)       # phase -> builds of programs not built before
    per_phase = defaultdict(list)
    for b in builds:
        per_phase[b["phase"]].append(b)
        key = (b["stage"], b["program"], b["ps"])
        if key not in seen:
            seen.add(key)
            first_in[b["phase"]].append(b)

    md = ["# Pipeline builds by phase", "",
          f"{len(builds)} builds of {len(seen)} distinct programs over {builds[-1]['t']:.0f} s. "
          "\"On first use\" means a dispatch or draw waited for the build (a stall the title sees).", ""]
    md.append("| phase | starts at (s) | builds | new programs | total build time (s) | on first use (s) |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for at, name in phases:
        bs = per_phase.get(name, [])
        total = sum(b["ms"] or 0 for b in bs) / 1000.0
        stall = sum(b["ms"] or 0 for b in bs if stalls(b)) / 1000.0
        md.append(f"| {name} | {at:.0f} | {len(bs)} | {len(first_in.get(name, []))} | {total:.1f} | {stall:.1f} |")
    md.append("")
    for at, name in phases:
        bs = sorted(first_in.get(name, []), key=lambda b: -(b["ms"] or 0))
        if not bs:
            continue
        with open(os.path.join(a.out, f"preload_{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}.txt"), "w",
                  encoding="utf-8", newline="\n") as f:
            for b in bs:
                f.write(f"{b['program']}\n" if b["ps"] in ("-", "") else f"{b['program']} {b['ps']}\n")
        md.append(f"## {name}: slowest new programs")
        md.append("")
        md.append("| program | ps | stage | origin | ms |")
        md.append("|---|---|---|---|---:|")
        for b in bs[:15]:
            ms = "-" if b["ms"] is None else f"{b['ms']:.0f}"
            md.append(f"| {b['program']} | {b['ps']} | {b['stage']} | {b['origin']} | {ms} |")
        md.append("")
    with open(os.path.join(a.out, "pso_phases.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md) + "\n")
    print(f"{len(builds)} builds, {len(seen)} programs, {len(phases)} phases -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
