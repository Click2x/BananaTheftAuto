#pragma once
// Banana Theft Auto: how far the pipeline compile queue has got, for the loading bar the presenter draws and the
// window caption. The queue counts each job it takes and each job it finishes or drops; a loading phase runs from the
// moment the backlog leaves zero until it is back at zero.
#include <atomic>
#include <cstdint>
#include <cstdlib>

namespace leonida::loading {

inline std::atomic<std::uint64_t> queued{0};
inline std::atomic<std::uint64_t> finished{0};

inline void job_queued() { queued.fetch_add(1, std::memory_order_relaxed); }
inline void job_finished() { finished.fetch_add(1, std::memory_order_relaxed); }

// LEONIDA_LOADING_BAR=0 turns the bar and the caption percentage off.
inline bool enabled() {
    static const bool on = [] {
        const char* v = std::getenv("LEONIDA_LOADING_BAR");
        return !(v && v[0] == '0');
    }();
    return on;
}

// The current phase's progress in [0, 1], or a negative value when nothing is loading. Several readers may call it;
// each keeps its own phase start.
struct Phase {
    std::uint64_t base_queued = 0, base_finished = 0;
    bool loading = false;

    double progress() {
        const std::uint64_t q = queued.load(std::memory_order_relaxed);
        const std::uint64_t f = finished.load(std::memory_order_relaxed);
        if (f >= q) {  // backlog drained: the next job starts a new phase
            loading = false;
            base_queued = q;
            base_finished = f;
            return -1.0;
        }
        if (!loading) {
            loading = true;
            base_finished = f;
            if (base_queued > f) base_queued = f;
        }
        const double total = double(q - base_queued), done = double(f - base_finished);
        return total > 0 ? (done < total ? done / total : 1.0) : 0.0;
    }
};

}  // namespace leonida::loading
