"""restore_interp_p2_f16_dst_hi: llvm-mc drops v_interp_p2_f16's op_sel destination bit (bit 14); the encoding check
restores it as `dst_hi` instead of refusing the shader. Encodings are synthetic (not from the game)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import rdna2spirv  # noqa: E402

PRINTED = bytes.fromhex("01005ad700000000")          # VOP3 word with op_sel bit 14 clear
WITH_BIT = bytes.fromhex("01405ad700000000")         # the same word with bit 14 set


class InterpDstHi(unittest.TestCase):
    def ins(self, op="v_interp_p2_f16"):
        return {"op": op, "mods": [], "args": []}

    def test_restores_only_bit_14(self):
        ins = self.ins()
        self.assertTrue(rdna2spirv.restore_interp_p2_f16_dst_hi(ins, WITH_BIT, PRINTED))
        self.assertIn("dst_hi", ins["mods"])

    def test_other_differences_are_still_refused(self):
        other = bytes.fromhex("01405ad700000001")
        self.assertFalse(rdna2spirv.restore_interp_p2_f16_dst_hi(self.ins(), other, PRINTED))
        self.assertFalse(rdna2spirv.restore_interp_p2_f16_dst_hi(self.ins(), PRINTED, WITH_BIT))

    def test_other_ops_are_untouched(self):
        self.assertFalse(rdna2spirv.restore_interp_p2_f16_dst_hi(self.ins("v_interp_p2_f32"), WITH_BIT, PRINTED))


if __name__ == "__main__":
    unittest.main()
