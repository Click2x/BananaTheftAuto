// LOCAL DIAGNOSTIC (LEONIDA_GPU_PROFILE=1): GPU time per compute program.
//
// A timestamp pair goes around every replayed compute dispatch, in a query pool taken from a ring the first time a
// command buffer dispatches. A pool is read back (never waited on) when the ring comes round to it again; a pool whose
// results are not all available yet is dropped from the count rather than waited for. Every 10 s the programs with
// the most GPU time since the start are printed with their share of all timed dispatch time.
#pragma once

#include <vulkan/vulkan.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace leonida::gpu_profile {

inline bool enabled() {
    static const bool on = [] {
        const char* v = std::getenv("LEONIDA_GPU_PROFILE");
        return v && *v && *v != '0';
    }();
    return on;
}

class Profiler {
public:
    static constexpr std::uint32_t kPools = 512;
    static constexpr std::uint32_t kStamps = 4096;  // commands timed per command buffer recording

    static Profiler& get() {
        static Profiler* p = new Profiler;
        return *p;
    }

    void initialize(VkDevice device, PFN_vkGetDeviceProcAddr get) {
        std::lock_guard lock(mutex_);
        if (device_ || !enabled()) return;
        device_ = device;
        create_ = reinterpret_cast<PFN_vkCreateQueryPool>(get(device, "vkCreateQueryPool"));
        results_ = reinterpret_cast<PFN_vkGetQueryPoolResults>(get(device, "vkGetQueryPoolResults"));
        reset_ = reinterpret_cast<PFN_vkCmdResetQueryPool>(get(device, "vkCmdResetQueryPool"));
        stamp_ = reinterpret_cast<PFN_vkCmdWriteTimestamp>(get(device, "vkCmdWriteTimestamp"));
        pools_.resize(kPools);
        std::fprintf(stderr, "[rt] gpu-profile: on (%u pools of %u commands)\n", kPools, kStamps);
    }
    void set_period(double ns_per_tick) { period_ = ns_per_tick; }
    void name(std::uintptr_t id, const char* shader) {
        if (!enabled() || !shader) return;
        std::lock_guard lock(mutex_);
        names_[id] = shader;
    }
    // The shader name given for a pipeline (empty when the profiler is off or none was given).
    std::string name_of(std::uintptr_t id) {
        std::lock_guard lock(mutex_);
        const auto it = names_.find(id);
        return it != names_.end() ? it->second : std::string();
    }

    // At the start of recording a command list into `cb` (outside any render pass): a fresh pool and the first stamp.
    void start(VkCommandBuffer cb) {
        if (!enabled() || !device_) return;
        std::lock_guard lock(mutex_);
        if (!period_) period_ = 1.0;  // the runtime did not say: NVIDIA's timestampPeriod (1 ns a tick)
        const std::uint32_t at = next_++ % kPools;
        Pool& pool = pools_[at];
        if (!pool.pool) {
            VkQueryPoolCreateInfo info{VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO};
            info.queryType = VK_QUERY_TYPE_TIMESTAMP;
            info.queryCount = kStamps + 1;
            if (create_(device_, &info, nullptr, &pool.pool) != VK_SUCCESS) return;
        } else {
            harvest(pool);
        }
        if (pool.cb) by_cb_.erase(pool.cb);
        pool.cb = cb;
        pool.used = 0;
        by_cb_[cb] = at;
        reset_(cb, pool.pool, 0, kStamps + 1);
        stamp_(cb, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, pool.pool, 0);
        report_maybe();
    }
    // After a command: its time is from the previous stamp to this one. key: what it was (kind << 56 | pipeline id).
    void after(VkCommandBuffer cb, std::uint64_t key) {
        if (!enabled() || !device_) return;
        std::lock_guard lock(mutex_);
        const auto it = by_cb_.find(cb);
        if (it == by_cb_.end()) return;
        Pool& pool = pools_[it->second];
        if (pool.cb != cb || pool.used >= kStamps) return;
        pool.keys[pool.used++] = key;
        stamp_(cb, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, pool.pool, pool.used);
    }

private:
    struct Pool {
        VkQueryPool pool = VK_NULL_HANDLE;
        VkCommandBuffer cb = VK_NULL_HANDLE;
        std::uint32_t used = 0;
        std::array<std::uint64_t, kStamps> keys{};
    };
    struct Total {
        double ns = 0;
        std::uint64_t count = 0;
    };

    void harvest(Pool& pool) {
        if (!pool.used) return;
        std::vector<std::uint64_t> raw(2 * (std::size_t(pool.used) + 1));
        const VkResult r = results_(device_, pool.pool, 0, pool.used + 1, raw.size() * 8, raw.data(), 16,
                                    VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WITH_AVAILABILITY_BIT);
        if (r == VK_SUCCESS || r == VK_NOT_READY) {
            for (std::uint32_t i = 0; i < pool.used; ++i) {
                const std::uint64_t t0 = raw[2 * i], a0 = raw[2 * i + 1], t1 = raw[2 * i + 2], a1 = raw[2 * i + 3];
                if (!a0 || !a1 || t1 < t0) {
                    ++dropped_;
                    continue;
                }
                const std::uint64_t key = pool.keys[i];
                const double ns = double(t1 - t0) * period_;
                Total& t = totals_[key];
                t.ns += ns;
                ++t.count;
                Total& k = kinds_[key >> 56];
                k.ns += ns;
                ++k.count;
                all_ns_ += ns;
            }
        }
        pool.used = 0;
    }

    static const char* kind_name(std::uint64_t k) {
        static const char* names[] = {"TransitionBarrier", "UavBarrier", "AliasingBarrier", "GlobalBarrier",
            "BufferBarrier", "TextureBarrier", "ClearRenderTarget", "ClearDepthStencil", "CopyBuffer", "CopyTexture",
            "CopyResource", "ResolveSubresource", "Predication", "ClearUnorderedAccess", "DiscardResource",
            "WriteImmediate", "LabelWrite", "AtomicCopyBuffer", "BeginQuery", "EndQuery", "ResolveQueries",
            "DebugMarker", "ExecuteIndirect", "BuildAccelerationStructure", "Dispatch", "Draw",
            "CopyAccelerationStructure", "AccelerationStructurePostbuild", "IndirectRasterDraw"};
        return k < sizeof(names) / sizeof(names[0]) ? names[k] : "?";
    }

    void report_maybe() {
        const auto now = std::chrono::steady_clock::now();
        if (now - last_report_ < std::chrono::seconds(20)) return;
        last_report_ = now;
        if (all_ns_ <= 0) return;
        std::vector<std::pair<std::uint64_t, Total>> kinds(kinds_.begin(), kinds_.end());
        std::sort(kinds.begin(), kinds.end(), [](const auto& a, const auto& b) { return a.second.ns > b.second.ns; });
        std::fprintf(stderr, "[rt] gpu-profile: %.1f s of timed GPU time, %llu dropped; by command kind:\n",
                     all_ns_ / 1e9, static_cast<unsigned long long>(dropped_));
        for (const auto& [k, t] : kinds)
            if (t.ns >= all_ns_ * 0.005)
                std::fprintf(stderr, "[rt] gpu-profile:   %5.1f%%  %9.1f ms  %8llu x  %s\n", 100.0 * t.ns / all_ns_,
                             t.ns / 1e6, static_cast<unsigned long long>(t.count), kind_name(k));
        std::vector<std::pair<std::uint64_t, Total>> top(totals_.begin(), totals_.end());
        std::sort(top.begin(), top.end(), [](const auto& a, const auto& b) { return a.second.ns > b.second.ns; });
        std::fprintf(stderr, "[rt] gpu-profile: top commands by pipeline:\n");
        for (std::size_t n = 0; n < top.size() && n < 20; ++n) {
            const auto& [key, t] = top[n];
            const auto name = names_.find(std::uintptr_t(key & ((std::uint64_t(1) << 56) - 1)));
            std::fprintf(stderr, "[rt] gpu-profile:   %5.1f%%  %9.1f ms  %8llu x  %8.3f ms each  %s %s\n",
                         100.0 * t.ns / all_ns_, t.ns / 1e6, static_cast<unsigned long long>(t.count),
                         t.ns / 1e6 / double(std::max<std::uint64_t>(1, t.count)), kind_name(key >> 56),
                         name != names_.end() ? name->second.c_str() : "");
        }
    }

    std::mutex mutex_;
    VkDevice device_ = VK_NULL_HANDLE;
    PFN_vkCreateQueryPool create_ = nullptr;
    PFN_vkGetQueryPoolResults results_ = nullptr;
    PFN_vkCmdResetQueryPool reset_ = nullptr;
    PFN_vkCmdWriteTimestamp stamp_ = nullptr;
    double period_ = 0;
    std::vector<Pool> pools_;
    std::unordered_map<VkCommandBuffer, std::uint32_t> by_cb_;
    std::uint32_t next_ = 0;
    std::unordered_map<std::uint64_t, Total> totals_, kinds_;
    std::unordered_map<std::uintptr_t, std::string> names_;
    double all_ns_ = 0;
    std::uint64_t dropped_ = 0;
    std::chrono::steady_clock::time_point last_report_{};
};

}  // namespace leonida::gpu_profile
