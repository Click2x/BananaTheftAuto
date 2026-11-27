// A pipeline cache that survives a crash, for the pipelines the offline corpus does not have (RT-HEAVY-PIPELINE-CACHE).
//
// The offline seed (pipeline_cache.bin, several GiB) covers what the `pipelines` build stage creates. A pipeline it
// misses is compiled on the spot, and some of those take the driver seconds each. pipeline_cache.session.bin cannot
// keep them across a crash: it is written at device teardown only, and a cache seeded from the corpus returns the
// whole corpus, over its write limit, so it is not written at all.
//
// So a pipeline is first created against the corpus cache with VK_PIPELINE_CREATE_FAIL_ON_PIPELINE_COMPILE_REQUIRED.
// When the driver would have to compile, it is created again against a cache of its own, seeded from
// pipeline_cache.heavy.bin. That cache holds only the corpus's misses, so it stays small. After a compile that took
// at least LEONIDA_HEAVY_PIPELINE_CACHE_MS (default 500 ms), it is written back to disk on a thread of its own: a
// staging file renamed over the old one, so a crash at any point leaves the last complete file.
//
// This header holds the pure decisions (the threshold and when to write). Vulkan and the file live in the device.
#pragma once

#include <cstdint>
#include <cstdlib>

namespace leonida::heavy_pipeline_cache {

inline constexpr std::uint32_t default_threshold_ms = 500;

struct Threshold {
    std::uint32_t ms = default_threshold_ms;  // 0: off
    bool valid = true;                        // false: the text was not a number; ms stays the default
};

// LEONIDA_HEAVY_PIPELINE_CACHE_MS: a compile at least this long schedules a write; 0 turns the heavy cache off.
inline Threshold parse_threshold(const char* text) {
    if (!text || !*text) return {};
    std::uint64_t value = 0;
    for (const char* p = text; *p; ++p) {
        if (*p < '0' || *p > '9') return {default_threshold_ms, false};
        value = value * 10 + std::uint64_t(*p - '0');
        if (value > 3'600'000) return {default_threshold_ms, false};  // an hour: past it the text is a mistake
    }
    return {std::uint32_t(value), true};
}

// When the writer thread writes. A heavy compile marks the cache dirty; the write waits `settle_ms` after the
// newest one (heavy compiles come in bursts at a load, and each write copies the whole heavy cache) but never more
// than `max_delay_ms` after the first unwritten one, so a long burst is still saved as it goes.
class WriteSchedule {
public:
    static constexpr std::uint64_t settle_ms = 3000;
    static constexpr std::uint64_t max_delay_ms = 20000;

    void note_heavy(std::uint64_t now_ms) {
        if (!dirty_) first_ = now_ms;
        dirty_ = true;
        last_ = now_ms;
    }
    bool dirty() const { return dirty_; }
    // The time to write at; only meaningful while dirty.
    std::uint64_t due_ms() const {
        const std::uint64_t settled = last_ + settle_ms, latest = first_ + max_delay_ms;
        return settled < latest ? settled : latest;
    }
    bool due(std::uint64_t now_ms) const { return dirty_ && now_ms >= due_ms(); }
    // A write started at `started_ms` took the cache as it was then: a heavy compile noted later than that keeps
    // the cache dirty for the next write.
    void written(std::uint64_t started_ms) {
        if (last_ <= started_ms) dirty_ = false;
        else first_ = started_ms;
    }

private:
    bool dirty_ = false;
    std::uint64_t first_ = 0, last_ = 0;
};

}  // namespace leonida::heavy_pipeline_cache
