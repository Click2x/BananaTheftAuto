"""tools/pso_timeline.py: phases, first builds, stalls and preload lists from synthetic pso-driver lines."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import pso_timeline  # noqa: E402

LOG = """\
[rt] pso-driver begin id=1 unix_ms=1000 stage=cs origin=warmup program=lib_cs_00001 ps=- mask=0
[rt] pso-driver end id=1 unix_ms=1100 us=100000 cpu_us=90000 result=0
[rt] pso-driver begin id=2 unix_ms=61000 stage=cs origin=dispatch program=lib_cs_00002 ps=- mask=0
[rt] pso-driver end id=2 unix_ms=68000 us=7000000 cpu_us=6900000 result=0
[rt] pso-driver begin id=3 unix_ms=62000 stage=gfx origin=draw program=lib_vs_00003 ps=lib_ps_00004 mask=0
[rt] pso-driver end id=3 unix_ms=62500 us=500000 cpu_us=400000 result=0
[rt] pso-driver begin id=4 unix_ms=70000 stage=cs origin=dispatch program=lib_cs_00001 ps=- mask=0
"""


class PsoTimeline(unittest.TestCase):
    def run_tool(self, *extra):
        d = tempfile.mkdtemp()
        log = os.path.join(d, "raw.txt")
        with open(log, "w", encoding="utf-8") as f:
            f.write(LOG)
        out = os.path.join(d, "out")
        self.assertEqual(pso_timeline.main([log, "--out", out, *extra]), 0)
        return out

    def test_phases_and_preload_lists(self):
        out = self.run_tool("--phase", "boot@0", "--phase", "loading@50")
        with open(os.path.join(out, "preload_loading.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read().split("\n")[:2], ["lib_cs_00002", "lib_vs_00003 lib_ps_00004"])
        with open(os.path.join(out, "preload_boot.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "lib_cs_00001")
        with open(os.path.join(out, "pso_phases.md"), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("| loading | 50 | 3 | 2 | 7.5 | 7.5 |", md)   # the unfinished build counts, with no time

    def test_windows_without_phases(self):
        out = self.run_tool("--window", "30")
        self.assertTrue(os.path.isfile(os.path.join(out, "preload_t0060-0090s.txt")))


if __name__ == "__main__":
    unittest.main()
