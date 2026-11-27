// Process-wide counts of calls recorded and replay attempts. A command list can replay more than once.
#pragma once
#include <atomic>
#include <cstdio>

namespace leonida::indirect_stats {
enum class Event { recorded, emitted, record_skip, replay_skip };
// One flag per reason, shared across resolver instantiations.
enum Reason { compound, disabled, pipeline, root_layout, viewport, mesh, topology, first_instance, entry, robust_index,
              count_limit, multi_draw, count_feature, raw_count_limit, argument_usage, count_usage,
              divisor, pending_pipeline, index_view, index_range, stateless, reason_count };
inline constexpr const char* reason_names[]{"compound signature", "opt-out", "missing pipeline", "missing root signature",
    "empty viewport", "mesh indirect", "topology", "drawIndirectFirstInstance", "missing Vulkan entry point",
    "robust sized index binding", "maxDrawIndirectCount", "multiDrawIndirect", "drawIndirectCount",
    "counted draw requires maxDrawIndirectCount == UINT32_MAX", "argument buffer lacks indirect creation usage",
    "count buffer lacks indirect creation usage", "nonunit vertex divisor", "pipeline pending",
    "invalid index view", "index view outside buffer or misaligned", "legacy command has no graphics state"};
static_assert(sizeof(reason_names) / sizeof(*reason_names) == reason_count);
// Topologies an indirect draw can replay without changing its vertex or index count: POINTLIST(1), LINELIST(2),
// LINESTRIP(3), TRIANGLELIST(4), TRIANGLESTRIP(5), the *_ADJ ones (10..13) and the console's RECTLIST(17, drawn
// through the geometry stage as direct draws are). UNDEFINED, QUADLIST(19) and patch lists stay skipped.
inline constexpr bool topology_supported(unsigned value) {
    return (value >= 1 && value <= 5) || (value >= 10 && value <= 13) || value == 17;
}
// Skips by reason, for the report (Banana Theft Auto).
inline std::atomic<unsigned long long>* skips_by_reason() {
    static std::atomic<unsigned long long> counts[reason_count]{};
    return counts;
}
struct Counts {
    std::atomic<unsigned long long> values[4]{};
    void report() const {
        std::fprintf(stderr, "[rt] indirect graphics: recorded=%llu emitted=%llu record_skips=%llu replay_skips=%llu",
                     values[0].load(), values[1].load(), values[2].load(), values[3].load());
        for (int r = 0; r < reason_count; ++r)
            if (const auto n = skips_by_reason()[r].load()) std::fprintf(stderr, "; %s %llu", reason_names[r], n);
        std::fputc('\n', stderr);
    }
    ~Counts() {
        for (const auto& value : values) {
            if (value.load()) {
                report();
                break;
            }
        }
    }
};
inline void note(Event event) {
    static Counts counts;
    const auto n = 1 + counts.values[static_cast<unsigned>(event)].fetch_add(1, std::memory_order_relaxed);
    if ((n & (n - 1)) == 0) counts.report();
}
inline void skip(Event event, Reason reason) {
    skips_by_reason()[reason].fetch_add(1, std::memory_order_relaxed);
    static std::atomic_flag shown[reason_count]{};
    if (!shown[reason].test_and_set(std::memory_order_relaxed))
        std::fprintf(stderr, "[rt] indirect graphics skipped: %s\n", reason_names[reason]);
    note(event);
}
}
