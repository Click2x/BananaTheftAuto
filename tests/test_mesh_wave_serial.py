"""--mesh-wave-serial: a 128-thread NGG mesh shader run as one 64-invocation workgroup that executes wave 0, then wave 1,
must write the same mesh outputs (counts, positions, clip distances, params, primitive indices, the null-primitive
cull bit) as the console's two concurrent waves.

The reference is today's translation (--wave64-emulate: the whole 128-invocation group in emulation rounds, both
waves concurrently), run with 32-wide subgroups as on NVIDIA. The serial translation (--wave64-emulate
--mesh-wave-serial) runs 64 invocations, also with 32-wide subgroups. Both execute in tests/semantic/spirv_mini_interp.run_workgroup; outputs are compared
per vertex / primitive index (index j belongs to invocation j in the reference and to invocation j % 64 in the
serial form, which writes j and j + 64). The listing is generated here with its encodings (only the branches' bytes
matter to the translator; the others give the instruction sizes), so neither llvm-mc nor pytest is needed:
`python -I tests/test_mesh_wave_serial.py` runs the same checks.
"""
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "tests", "semantic")):
    if p not in sys.path:
        sys.path.insert(0, p)

import rdna2spirv  # noqa: E402
import spirv_mini_interp  # noqa: E402

SOPP = {"s_endpgm": 1, "s_branch": 2, "s_cbranch_scc0": 4, "s_cbranch_scc1": 5, "s_cbranch_vccz": 6,
        "s_cbranch_vccnz": 7, "s_cbranch_execz": 8, "s_cbranch_execnz": 9, "s_barrier": 10, "s_sendmsg": 16}


def _dxbc(chunks):
    head = 32 + 4 * len(chunks)
    offsets, body = [], b""
    for fourcc, payload in chunks:
        offsets.append(head + len(body))
        body += fourcc + struct.pack("<I", len(payload)) + payload
    return (b"DXBC" + bytes(16) + struct.pack("<III", 1, head + len(body), len(chunks))
            + b"".join(struct.pack("<I", o) for o in offsets) + body)


def _psv0(threads=(128, 1, 1), maxv=128, maxp=128):
    r = bytearray(48)
    struct.pack_into("<HH", r, 12, maxv, maxp)
    r[24] = 13          # mesh
    r[27] = 2           # triangles
    struct.pack_into("<III", r, 36, *threads)
    return b"PSV0", struct.pack("<I", len(r)) + bytes(r)


def _osg1(elements):
    out = struct.pack("<II", len(elements), 8)
    for reg, sysv, mask in elements:
        out += struct.pack("<6I", 0, 0, 0, sysv, 3, reg) + bytes([mask, mask, 0, 0]) + struct.pack("<I", 0)
    return b"OSG1", out


def _program(nv, np_, clip):
    """The NGG shape of the corpus (e.g. MSNC_VS_LinearDepthSkin): lane-divergent exec regions with a
    v_readfirstlane, a wave-uniform branch on the wave id, a whole-wave vote (s_bcnt1 of VCC), a scalar loop, then
    the epilogue: lane 0 of wave 0 sends GS_ALLOC_REQ (m0 = nv | np << 12), the two s_barrier (the first one only on
    the zero-primitive path), the primitive export with the null bit and the vertex exports."""
    P = []

    def i(text, size=4):
        P.append(("i", text, size))

    def br(op, label):
        P.append(("b", op, label))

    def lab(name):
        P.append(("l", name))

    i("s_mov_b64 exec, -1")
    i("v_mbcnt_lo_u32_b32 v0, -1, 0", 8)
    i("s_bfe_u32 s1, s3, 0x40018", 8)
    i("v_mbcnt_hi_u32_b32 v0, -1, v0", 8)
    i("v_lshl_add_u32 v0, s1, 6, v0", 8)               # v0 = thread id in the group (0..127)
    i("v_readfirstlane_b32 s0, v5")                    # group * 128 + wave * 64
    i(f"s_movk_i32 s78, 0x{nv:x}")
    i(f"s_movk_i32 s79, 0x{np_:x}")
    i("v_cvt_f32_u32_e32 v1, v0")
    i("v_cvt_f32_u32_e32 v2, v5")
    i("v_mul_f32_e32 v3, 0.5, v1")
    i("v_add_f32_e32 v4, v2, v1")
    i("v_mov_b32_e32 v7, 1.0")
    i("v_mov_b32_e32 v8, 0")
    i("v_cvt_f32_u32_e32 v17, s0")
    i("v_and_b32_e32 v6, 3, v0")
    i("v_cmp_eq_u32_e32 vcc, 0, v6")
    i("s_and_saveexec_b64 s[4:5], vcc")
    br("s_cbranch_execz", "L1")
    i("v_mul_f32_e32 v7, 2.0, v1")
    i("v_readfirstlane_b32 s6, v0")                    # first active lane of this wave
    i("v_mov_b32_e32 v8, s6")
    lab("L1")
    i("s_or_b64 exec, exec, s[4:5]")
    i("s_cmp_eq_u32 s1, 1")
    br("s_cbranch_scc0", "L2")
    i("v_add_f32_e32 v3, 0x42c80000, v3", 8)          # wave 1 only: +100.0
    lab("L2")
    i("v_cmp_gt_u32_e32 vcc, 2, v6")
    i("s_bcnt1_i32_b64 s7, vcc")                       # lanes of this wave with v6 < 2
    i("v_cvt_f32_u32_e32 v9, s7")
    i("v_mov_b32_e32 v10, 0")
    i("s_mov_b32 s8, 3")
    lab("L3")
    i("v_add_f32_e32 v10, v10, v1")
    i("s_sub_u32 s8, s8, 1")
    i("s_cmp_lg_u32 s8, 0")
    br("s_cbranch_scc1", "L3")
    # epilogue
    i("s_cmp_eq_u32 s79, 0")
    i("s_cselect_b64 s[2:3], exec, 0")
    i("s_mov_b64 s[10:11], exec")
    i("s_lshl_b32 s12, s79, 12")
    i("s_or_b32 s12, s12, s78")
    i("v_cmpx_eq_u32_e32 0, v0")
    br("s_cbranch_execz", "L4")
    i("s_andn2_b64 vcc, exec, s[2:3]")
    i("s_mov_b32 m0, s12")
    P.append(("s", "s_sendmsg sendmsg(MSG_GS_ALLOC_REQ)", [0x09, 0x00, 0x90, 0xbf]))
    br("s_cbranch_vccnz", "L4")
    P.append(("s", "s_barrier", [0x00, 0x00, 0x8a, 0xbf]))
    i("v_bfrev_b32_e32 v1, 1")
    i("exp pos0 off, off, off, off done", 8)
    i("exp prim v1, off, off, off done", 8)
    lab("L4")
    i("s_mov_b64 exec, s[10:11]")
    P.append(("s", "s_barrier", [0x00, 0x00, 0x8a, 0xbf]))
    i("v_cmp_gt_u32_e32 vcc, s79, v0")
    i("s_and_saveexec_b64 s[6:7], vcc")
    br("s_cbranch_execz", "L5")
    i("v_add_nc_u32_e32 v11, 1, v0")
    i("v_add_nc_u32_e32 v12, 2, v0")
    i("v_lshlrev_b32_e32 v11, 10, v11")
    i("v_lshlrev_b32_e32 v12, 20, v12")
    i("v_or3_b32 v13, v0, v11, v12", 8)
    i("v_and_b32_e32 v14, 7, v0")
    i("v_cmp_eq_u32_e32 vcc, 5, v14")
    i("v_bfrev_b32_e32 v15, 1")
    i("v_cndmask_b32_e32 v15, 0, v15, vcc")
    i("v_or_b32_e32 v13, v13, v15")                    # null primitive for thread % 8 == 5
    i("exp prim v13, off, off, off done", 8)
    lab("L5")
    i("s_mov_b64 exec, s[6:7]")
    i("v_cmp_gt_u32_e32 vcc, s78, v0")
    i("s_and_saveexec_b64 s[0:1], vcc")
    br("s_cbranch_execz", "L6")
    i("v_mov_b32_e32 v16, 1.0")
    i("exp pos0 v3, v4, v7, v16 done", 8)
    if clip:
        i("exp pos1 v17, off, off, off done", 8)
    i("exp param0 v8, v9, v10, off", 8)
    i("exp param1 v2, v1, off, off", 8)
    lab("L6")
    P.append(("s", "s_endpgm", [0x00, 0x00, 0x81, 0xbf]))

    pcs, pc = {}, 0
    for item in P:
        if item[0] == "l":
            pcs[item[1]] = pc
        else:
            pc += item[2] if item[0] == "i" else 4
    lines, pc = [], 0
    for item in P:
        if item[0] == "l":
            continue
        if item[0] == "i":
            enc = [0] * item[2]
            text = item[1]
        elif item[0] == "s":
            enc, text = item[2], item[1]
        else:
            imm = (pcs[item[2]] - (pc + 4)) // 4
            u = imm & 0xFFFF
            enc = [u & 0xFF, u >> 8, 0x80 | SOPP[item[1]], 0xbf]
            text = f"{item[1]} {imm}"
        lines.append(f"\t{text} ; encoding: [{','.join(f'0x{b:02x}' for b in enc)}]")
        pc += len(enc)
    return "\n".join(lines) + "\n"


def _translate(work, name, asm, dxbc, emulate, serial):
    os.makedirs(os.path.join(work, "disasm"), exist_ok=True)
    with open(os.path.join(work, name + ".dxbc"), "wb") as f:
        f.write(dxbc)
    path = os.path.join(work, "disasm", name + ".s")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"; {name}  synthetic\n{asm}")
    saved = rdna2spirv.WAVE64_EMULATE, rdna2spirv.MESH_WAVE_SERIAL
    try:
        rdna2spirv.WAVE64_EMULATE, rdna2spirv.MESH_WAVE_SERIAL = emulate, serial
        text = rdna2spirv.translate(path)
        return text, rdna2spirv.translate.last_gen
    finally:
        rdna2spirv.WAVE64_EMULATE, rdna2spirv.MESH_WAVE_SERIAL = saved


def _per_index(outs, var, owner, n):
    """Element j (of n) of the arrayed output `var`, taken from the invocation that owns index j."""
    rows = []
    for j in range(n):
        words = outs[owner(j)][var]
        k = len(words) // 128
        rows.append(words[k * j:k * (j + 1)])
    return rows


def run_case(nv, np_, clip=False, group=3):
    name = "ms_ws_case"
    dxbc = _dxbc([_psv0()] + ([_osg1([(0, 1, 0xF), (1, 2, 0x1)])] if clip else []))
    asm = _program(nv, np_, clip)
    with tempfile.TemporaryDirectory() as work:
        ref, rg = _translate(work, name, asm, dxbc, emulate=True, serial=False)
        ser, g = _translate(work, name, asm, dxbc, emulate=True, serial=True)
    assert not rg.ms_ws and "LocalSize 128 1 1" in ref
    assert g.ms_ws and g.emulate_plan is not None and g.emulate_plan["mode"] == "inline_all"
    assert "OpExecutionMode %main LocalSize 64 1 1" in ser and "OpSwitch" not in ser
    base = {"%wg_id": (group, 0, 0), "%num_wg": (8, 1, 1)}
    _, ref_out = spirv_mini_interp.run_workgroup(
        ref, 128, 32, inputs_for=lambda i: dict(base, **{"%local_index": i, "%sg_lane": i % 32}),
        return_outputs=True)
    _, ser_out = spirv_mini_interp.run_workgroup(
        ser, 64, 32, inputs_for=lambda i: dict(base, **{"%local_index_hw": i, "%sg_lane": i % 32}),
        return_outputs=True)
    counts = ref_out[0]["OpSetMeshOutputsEXT"]
    assert all(o["OpSetMeshOutputsEXT"] == counts for o in ref_out + ser_out), "vertex / primitive counts differ"
    assert counts == (min(nv, 128), min(np_, 128)), counts
    msv, msp = counts
    vtx_vars = [v for v in ref_out[0] if v in ("%ms_out_pos", "%ms_out_vtx") or v.startswith("%ms_out_param")]
    prim_vars = [v for v in ref_out[0] if v in ("%ms_prim_idx", "%ms_cull")]
    assert ("%ms_out_vtx" in vtx_vars) == clip and len(vtx_vars) == 3 and len(prim_vars) == 2, vtx_vars + prim_vars
    for var, n in [(v, msv) for v in vtx_vars] + [(v, msp) for v in prim_vars]:
        a = _per_index(ref_out, var, lambda j: j, n)
        b = _per_index(ser_out, var, lambda j: j % 64, n)
        for j in range(n):
            assert a[j] == b[j], f"{var}[{j}]: reference {a[j]} serial {b[j]} (nv={nv}, np={np_})"
    nulls = sum(1 for row in _per_index(ref_out, "%ms_cull", lambda j: j, msp) if row[0])
    return counts, nulls


CASES = [(128, 128, False), (100, 90, False), (65, 30, False), (64, 64, False), (37, 21, False), (3, 1, False),
         (128, 126, True), (40, 64, True)]


def test_mesh_wave_serial_matches_wave64():
    for nv, np_, clip in CASES:
        run_case(nv, np_, clip)


def test_mesh_wave_serial_qualification():
    """Only the epilogue-only shape qualifies: LDS, a store, a third barrier or a second ALLOC_REQ keep the round
    emulation of the whole group."""
    psv = {"threads": 128, "size": (128, 1, 1)}

    def ins(op, t=None, pc=0):
        return {"op": op, "args": [{"k": "special", "t": t}] if t else [], "mods": [], "pc": pc}

    good = [ins("v_mov_b32_e32", pc=0), ins("s_sendmsg", "sendmsg(MSG_GS_ALLOC_REQ)", 4),
            ins("s_barrier", pc=8), ins("s_barrier", pc=12)]
    assert rdna2spirv.mesh_wave_serial_ok(good, psv)
    assert not rdna2spirv.mesh_wave_serial_ok(good, {"threads": 64, "size": (64, 1, 1)})
    assert not rdna2spirv.mesh_wave_serial_ok(good + [ins("ds_write_b32", pc=16)], psv)
    assert not rdna2spirv.mesh_wave_serial_ok(good + [ins("buffer_store_dword", pc=16)], psv)
    assert not rdna2spirv.mesh_wave_serial_ok(good + [ins("s_barrier", pc=16)], psv)
    assert not rdna2spirv.mesh_wave_serial_ok(good + [ins("s_sendmsg", "sendmsg(MSG_GS_ALLOC_REQ)", 16)], psv)
    assert not rdna2spirv.mesh_wave_serial_ok([ins("s_barrier", pc=0)] + good[1:3], psv)


def test_mesh_wave_serial_off_by_default():
    asm = _program(100, 90, False)
    with tempfile.TemporaryDirectory() as work:
        text, g = _translate(work, "ms_ws_case", asm, _dxbc([_psv0()]), emulate=True, serial=False)
    assert not g.ms_ws and "LocalSize 128 1 1" in text and "%local_index_hw" not in text


if __name__ == "__main__":
    for nv, np_, clip in CASES:
        print(f"nv={nv:3} np={np_:3} clip={clip!s:5} -> counts, null prims:", run_case(nv, np_, clip))
    test_mesh_wave_serial_qualification()
    test_mesh_wave_serial_off_by_default()
    print("ok")
