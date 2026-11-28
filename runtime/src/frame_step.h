#pragma once

// The title's time step from the measured frame time at any frame rate: LEONIDA_TIME_STEP (default `measured`;
// `stock` keeps the title's own step), applied to the mapped executable before any of its code runs.
//
// How the 1.0.2.1 title makes its step (measured by static analysis and under VIctory; RVAs below, in the style of
// display_profile.h): once a frame its timer takes the frame's real time from QueryPerformanceCounter (the previous
// count's difference times 1 / QueryPerformanceFrequency) and gives every one of its time sets (game time, game time
// not paused, camera, ...: a millisecond count, a frame count and the step in seconds) a step made from it:
//
//     step = max(nominal, min(1/15 s, measured)) * time scale      (re-clamped to [min step, 1/15 s] when scaled)
//
// `nominal` is one frame at the frame rate the title aims for (its settings' frame-rate cap, else the display's refresh
// over the vsync interval, else 30): 1/30 s. The cap is a 1/15 s constant. So the step is real only between 15 and 30 frames a second: above
// 30 every frame still steps 1/30 s and the world runs fps/30 times too fast (the doubled speed seen on the console when
// a glitch doubles the frame rate), below 15 every frame steps 1/15 s and the world runs at fps/15 of real time
// (0.13 at VIctory's 2 fps). The nominal floor is taken while a switch of the timer is set, which the retail build's
// init sets (the same switch picks where in the frame the timer runs); without it the floor is the timer's own minimum
// step, 1/3000 s, which its init writes.
//
// The patch moves two loads in each of the timer's two step computations (the time sets' and the camera's), keeping
// the code: the floor reads the timer's minimum step instead of the nominal frame time, and the cap reads the timer's
// own 1.0 constant instead of 1/15 s. The step is then the measured frame time between 1/3000 s and 1 s: real time
// from 1 to 3000 frames a second. Each load is checked against its stock bytes, and the two targets against theirs,
// before anything is written; another build is left alone (and says so). Frames longer than 1 s (a loading hitch)
// still step 1 s. The approach is BlueShell's for the same class of bug (the measured frame time at the engine's step,
// its commit 1a429f6); the check-then-patch shape is display_profile.h's.
//
// Measured under VIctory, the same four loads written into the running title (game time against the title's own
// unclipped real-time set and the wall clock): stock, 30 fps menus 1.00, a 42 fps loading screen 1.54, the world at
// 1.5 fps 0.15; patched, 30 fps 1.00, 70 fps 1.00, the world at 1.6 fps 1.00 over every frame under 1 s.
//
// Not changed: what counts frames instead of reading the step. The game time's frame count (the u32 after its
// millisecond count) has about 690 readers, nearly all "once a frame" or "N frames since" bookkeeping; a few turn
// frames into time and stay frame-paced at any rate, e.g. a blend over 15 frames (+0x8eee32: frames since times the
// 1/15 constant, at most 1) and a check of frames since times the current step against 0.5 s (+0x244b584).

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace leonida::frame_step {

// RVAs in the 1.0.2.1 retail executable. Each load is `vmovss xmmN, dword [rip + disp32]` (C5 FA 10 modrm disp32),
// 8 bytes long.
inline constexpr std::uint32_t kTimeSetCapLoadRva = 0x02226045;     // xmm3 = 1/15 s
inline constexpr std::uint32_t kTimeSetFloorLoadRva = 0x0222605a;   // xmm4 = nominal frame time
inline constexpr std::uint32_t kCameraCapLoadRva = 0x02226833;      // xmm0 = 1/15 s
inline constexpr std::uint32_t kCameraFloorLoadRva = 0x02226854;    // xmm1 = nominal frame time
// What they read: the 1/15 s constant (.rdata), the nominal frame time (.data, 1/30 until the settings set it).
inline constexpr std::uint32_t kStockCapRva = 0x06159ec0;
inline constexpr std::uint32_t kNominalRva = 0x06849844;
// What they read after the patch: the timer's 1.0 constant (.rdata) and its minimum step (.data: 1/30 in the file,
// 1/3000 s once the timer's init has run, before its first step).
inline constexpr std::uint32_t kOneRva = 0x05fc6ed8;
inline constexpr std::uint32_t kMinStepRva = 0x06847660;

inline constexpr std::uint32_t kLoadLength = 8;

struct Patch {
    std::uint32_t rva = 0;
    std::vector<std::uint8_t> stock;  // what must be there
    std::vector<std::uint8_t> bytes;  // what goes there (empty: only checked)
    const char* what = "";
};

namespace detail {
inline void put32(std::vector<std::uint8_t>& out, std::uint32_t v) {
    for (int i = 0; i < 4; ++i) out.push_back(std::uint8_t(v >> (8 * i)));
}
inline std::vector<std::uint8_t> float_bytes(float f) {
    std::uint32_t v = 0;
    std::memcpy(&v, &f, sizeof v);
    std::vector<std::uint8_t> out;
    put32(out, v);
    return out;
}
// `vmovss xmm<reg>, dword [rip + disp32]` at `at`, reading `target`.
inline std::vector<std::uint8_t> load(std::uint32_t at, std::uint8_t reg, std::uint32_t target) {
    std::vector<std::uint8_t> out{0xc5, 0xfa, 0x10, std::uint8_t(0x05 | (reg << 3))};
    put32(out, std::uint32_t(std::int32_t(target) - std::int32_t(at + kLoadLength)));
    return out;
}
}  // namespace detail

// The patches, in the order they are checked: the two targets' values (checked only), then the four loads.
inline std::vector<Patch> plan() {
    using detail::load;
    std::vector<Patch> p;
    p.push_back({kOneRva, detail::float_bytes(1.0f), {}, "timer's 1.0 constant"});
    p.push_back({kMinStepRva, detail::float_bytes(1.0f / 30.0f), {}, "timer's minimum step"});
    p.push_back({kTimeSetCapLoadRva, load(kTimeSetCapLoadRva, 3, kStockCapRva), load(kTimeSetCapLoadRva, 3, kOneRva),
                 "time sets' step cap"});
    p.push_back({kTimeSetFloorLoadRva, load(kTimeSetFloorLoadRva, 4, kNominalRva),
                 load(kTimeSetFloorLoadRva, 4, kMinStepRva), "time sets' step floor"});
    p.push_back({kCameraCapLoadRva, load(kCameraCapLoadRva, 0, kStockCapRva), load(kCameraCapLoadRva, 0, kOneRva),
                 "camera step cap"});
    p.push_back({kCameraFloorLoadRva, load(kCameraFloorLoadRva, 1, kNominalRva),
                 load(kCameraFloorLoadRva, 1, kMinStepRva), "camera step floor"});
    return p;
}

// LEONIDA_TIME_STEP: unset, empty or `measured` (any case): patch; `stock`, `0` or `off`: the title's own step.
// Anything else is refused (`*known` false) and patches as the default does.
inline bool wanted(const char* value, bool* known = nullptr) {
    if (known) *known = true;
    if (!value || !*value) return true;
    std::string v(value);
    for (char& c : v) c = char(c >= 'A' && c <= 'Z' ? c - 'A' + 'a' : c);
    if (v == "measured" || v == "1" || v == "on") return true;
    if (v == "stock" || v == "0" || v == "off") return false;
    if (known) *known = false;
    return true;
}

// True when every patch's stock bytes are in the image, read through `at(rva, length)` (a pointer to that many bytes
// of the image, or null past it); else false with `*error` set.
template <class Access>
bool check(Access&& at, const std::vector<Patch>& patches, std::string* error) {
    for (const Patch& patch : patches) {
        const std::uint8_t* there = at(patch.rva, patch.stock.size());
        if (!there || std::memcmp(there, patch.stock.data(), patch.stock.size()) != 0) {
            if (error) *error = std::string("the ") + patch.what + " is not the 1.0.2.1 executable's";
            return false;
        }
    }
    return true;
}

// check(), then every patch with bytes written through `at`. Nothing is written when the check fails.
template <class Access>
bool apply(Access&& at, const std::vector<Patch>& patches, std::string* error) {
    if (!check(at, patches, error)) return false;
    for (const Patch& patch : patches)
        if (!patch.bytes.empty()) std::memcpy(at(patch.rva, patch.bytes.size()), patch.bytes.data(), patch.bytes.size());
    return true;
}

#ifdef _WIN32
// apply() on a mapped image of `size` bytes at `base`: every place is made writable first (or nothing is written), then
// all are written, then the protections are put back in reverse order (two loads share a page: the second
// VirtualProtect saw the first one's writable protection) and the instruction cache flushed. All the loads or none: a
// floor without the cap (or the other way round) would still not be real time.
inline bool apply_to_image(std::uint8_t* base, std::uint32_t size, const std::vector<Patch>& patches,
                           std::string* error) {
    const auto at = [&](std::uint32_t rva, std::size_t length) -> std::uint8_t* {
        return std::uint64_t(rva) + length <= size ? base + rva : nullptr;
    };
    if (!check(at, patches, error)) return false;
    std::vector<DWORD> old(patches.size(), 0);
    for (std::size_t i = 0; i < patches.size(); ++i) {
        const Patch& patch = patches[i];
        if (patch.bytes.empty()) continue;
        if (!VirtualProtect(at(patch.rva, patch.bytes.size()), patch.bytes.size(), PAGE_EXECUTE_READWRITE, &old[i])) {
            for (std::size_t j = i; j-- > 0;)
                if (!patches[j].bytes.empty())
                    VirtualProtect(at(patches[j].rva, patches[j].bytes.size()), patches[j].bytes.size(), old[j], &old[j]);
            if (error) *error = std::string("the ") + patch.what + " could not be made writable";
            return false;
        }
    }
    for (const Patch& patch : patches)
        if (!patch.bytes.empty()) std::memcpy(at(patch.rva, patch.bytes.size()), patch.bytes.data(), patch.bytes.size());
    for (std::size_t i = patches.size(); i-- > 0;) {
        const Patch& patch = patches[i];
        if (patch.bytes.empty()) continue;
        std::uint8_t* where = at(patch.rva, patch.bytes.size());
        DWORD ignored = 0;
        VirtualProtect(where, patch.bytes.size(), old[i], &ignored);
        FlushInstructionCache(GetCurrentProcess(), where, patch.bytes.size());
    }
    return true;
}
#endif

}  // namespace leonida::frame_step
