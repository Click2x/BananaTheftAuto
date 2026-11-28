#pragma once
// Banana Theft Auto address guard (LEONIDA_ADDRESS_GUARD=1, with shaders translated by rdna2spirv.py
// --address-guard). Translated shaders reach memory at heap_base + a 48-bit offset; an offset that names no memory
// (a stale or never-filled pointer in title data) faults the GPU and loses the device. A guarded shader checks each
// such offset: inside the arena it passes; elsewhere a page table built here says whether a device-addressable buffer
// backs that 4 KiB page. A refused access goes to a zeroed sink in the arena instead.
//
// Layout, all relative to heap_base (the arena's device address):
//   [kHeaderOffset, +32)  header: magic, table offset (u64, two's complement), arena size (u64)
//   [kSinkOffset, kRegionEnd)  sink: refused accesses read and write here; zeroed before each submission
// Page table (its own buffer): level 1, 65536 u32 indexed by offset bits 47..32 (0: nothing backed in that 4 GiB,
// n: level-2 block n - 1); level 2 blocks of 2^20 bits, one per 4 KiB page, at kL1Bytes + (n - 1) * kBlockBytes.
// The shader side is Gen.guard_function in tools/rdna2spirv.py; the two must agree on these numbers.
#ifndef NOMINMAX
#define NOMINMAX  // std::min/std::max in every file that includes this header
#endif
#include <windows.h>
#include <vulkan/vulkan.h>

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <unordered_map>
#include <utility>
#include <vector>

namespace leonida::address_guard {

constexpr std::uint64_t kHeaderOffset = 0x70000;
constexpr std::uint64_t kSinkOffset = 0x71000;
constexpr std::uint64_t kRegionEnd = 0x80000;
constexpr std::uint32_t kMagic = 0x47414E42;  // "BNAG"
constexpr std::uint32_t kL1Entries = 65536;
constexpr std::uint64_t kL1Bytes = kL1Entries * 4;
constexpr std::uint64_t kBlockBytes = (1ull << 20) / 8;  // 2^20 pages of 4 KiB, one bit each
constexpr std::uint32_t kMaxBlocks = 96;
constexpr std::uint64_t kTableBytes = kL1Bytes + kMaxBlocks * kBlockBytes;

inline bool enabled() {
    static const bool on = [] {
        const char* v = std::getenv("LEONIDA_ADDRESS_GUARD");
        return v && v[0] == '1';
    }();
    return on;
}

// Every buffer created with SHADER_DEVICE_ADDRESS usage, by handle: its size and, once asked, its address.
struct Registry {
    std::mutex mutex;
    std::unordered_map<VkBuffer, std::pair<std::uint64_t, VkDeviceAddress>> buffers;
    std::atomic<std::uint64_t> version{1};
    PFN_vkCreateBuffer create = nullptr;
    PFN_vkDestroyBuffer destroy = nullptr;
    PFN_vkGetBufferDeviceAddress address = nullptr;
    // The last destroyed buffers that had an address (diagnostic: naming the shaders' refusals).
    struct Gone {
        VkDeviceAddress address = 0;
        std::uint64_t bytes = 0;
        unsigned long long at = 0;  // GetTickCount64
    };
    Gone gone[4096]{};
    std::uint64_t gone_next = 0;
};

inline Registry& registry() {
    static Registry r;
    return r;
}

inline VKAPI_ATTR VkResult VKAPI_CALL create_buffer(VkDevice device, const VkBufferCreateInfo* info,
                                                     const VkAllocationCallbacks* callbacks, VkBuffer* buffer) {
    Registry& r = registry();
    const VkResult result = r.create(device, info, callbacks, buffer);
    if (result == VK_SUCCESS && info && (info->usage & VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT)) {
        std::lock_guard lock(r.mutex);
        r.buffers[*buffer] = {info->size, 0};
    }
    return result;
}

inline VKAPI_ATTR void VKAPI_CALL destroy_buffer(VkDevice device, VkBuffer buffer,
                                                 const VkAllocationCallbacks* callbacks) {
    Registry& r = registry();
    {
        std::lock_guard lock(r.mutex);
        const auto it = r.buffers.find(buffer);
        if (it != r.buffers.end()) {
            if (it->second.second) {
                r.version.fetch_add(1, std::memory_order_release);
                r.gone[r.gone_next++ % 4096] = {it->second.second, it->second.first, GetTickCount64()};
            }
            r.buffers.erase(it);
        }
    }
    r.destroy(device, buffer, callbacks);
}

inline VKAPI_ATTR VkDeviceAddress VKAPI_CALL buffer_address(VkDevice device, const VkBufferDeviceAddressInfo* info) {
    Registry& r = registry();
    const VkDeviceAddress address = r.address(device, info);
    if (info) {
        std::lock_guard lock(r.mutex);
        const auto it = r.buffers.find(info->buffer);
        if (it != r.buffers.end() && it->second.second != address) {
            it->second.second = address;
            r.version.fetch_add(1, std::memory_order_release);
        }
    }
    return address;
}

// The latest destroyed buffer that held `address`, if any of the last 4096 did.
inline bool destroyed_holding(VkDeviceAddress address, Registry::Gone& out) {
    Registry& r = registry();
    std::lock_guard lock(r.mutex);
    bool found = false;
    for (const Registry::Gone& g : r.gone)
        if (g.bytes && address >= g.address && address - g.address < g.bytes && (!found || g.at > out.at)) {
            out = g;
            found = true;
        }
    return found;
}

// Diagnostic (device-fault reports): which buffer the registry knows at `address`. Writes one line into `out`:
// a live buffer (its address and size), the latest destroyed one that held it (how long ago), or none.
inline void describe(VkDeviceAddress address, char* out, std::size_t size) {
    Registry& r = registry();
    {
        std::lock_guard lock(r.mutex);
        for (const auto& [buffer, info] : r.buffers)
            if (info.second && address >= info.second && address - info.second < info.first) {
                std::snprintf(out, size, "in a live buffer at 0x%llx (%llu bytes, offset 0x%llx)",
                              (unsigned long long)info.second, (unsigned long long)info.first,
                              (unsigned long long)(address - info.second));
                return;
            }
    }
    Registry::Gone gone{};
    if (destroyed_holding(address, gone)) {
        std::snprintf(out, size, "in a buffer DESTROYED %llu ms before this report (at 0x%llx, %llu bytes)",
                      (unsigned long long)(GetTickCount64() - gone.at), (unsigned long long)gone.address,
                      (unsigned long long)gone.bytes);
        return;
    }
    // The nearest live buffers below and above, to tell a gap from an overrun.
    VkDeviceAddress below = 0, below_end = 0, above = ~0ull;
    {
        std::lock_guard lock(r.mutex);
        for (const auto& [buffer, info] : r.buffers) {
            if (!info.second) continue;
            if (info.second <= address && info.second > below) {
                below = info.second;
                below_end = info.second + info.first;
            }
            if (info.second > address && info.second < above) above = info.second;
        }
    }
    std::snprintf(out, size, "in no known buffer (nearest below ends at 0x%llx, %lld bytes before; next starts at 0x%llx)",
                  (unsigned long long)below_end, (long long)(address - below_end), (unsigned long long)above);
}

// Called by VulkanDeviceFunctions::load: routes buffer creation, destruction and address queries through the registry.
inline void wrap(PFN_vkCreateBuffer& create, PFN_vkDestroyBuffer& destroy, PFN_vkGetBufferDeviceAddress& address) {
    if (!enabled() || !create || !destroy || !address) return;
    Registry& r = registry();
    {
        std::lock_guard lock(r.mutex);
        if (!r.create) {
            r.create = create;
            r.destroy = destroy;
            r.address = address;
        }
    }
    if (create == r.create) create = &create_buffer;
    if (destroy == r.destroy) destroy = &destroy_buffer;
    if (address == r.address) address = &buffer_address;
}

// The CPU side of the page table: built from the registry, then the words that changed are written to the GPU copy.
class Table {
public:
    // Rebuilds from every registered buffer outside [heap_base, heap_base + arena_size). Returns false when nothing
    // changed since the last build.
    bool rebuild(VkDeviceAddress heap_base, std::uint64_t arena_size) {
        Registry& r = registry();
        const std::uint64_t version = r.version.load(std::memory_order_acquire);
        if (version == built_version_ && heap_base == heap_base_) return false;
        std::vector<std::pair<std::uint64_t, std::uint64_t>> ranges;  // [offset, end) relative to heap_base
        {
            std::lock_guard lock(r.mutex);
            ranges.reserve(r.buffers.size());
            for (const auto& [buffer, info] : r.buffers)
                if (info.second && info.first) ranges.push_back({info.second - heap_base, info.first});
        }
        std::vector<std::uint32_t> l1(kL1Entries, 0);
        std::vector<std::uint32_t> blocks;
        std::uint32_t used = 0;
        overflow_ = false;
        for (const auto& [offset, bytes] : ranges) {
            if (bytes > (16ull << 30)) continue;  // past 16 GiB is not a buffer the shaders read
            const std::uint64_t start = offset & ((1ull << 48) - 1);
            if (start < arena_size && start + bytes <= arena_size) continue;  // the arena passes on its own
            for (std::uint64_t page = start >> 12, last = ((start + bytes - 1) & ((1ull << 48) - 1)) >> 12;
                 page <= last; ++page) {
                const std::uint32_t chunk = std::uint32_t(page >> 20) & 0xFFFF;
                if (!l1[chunk]) {
                    if (used == kMaxBlocks) {
                        overflow_ = true;
                        break;
                    }
                    l1[chunk] = ++used;
                    blocks.resize(std::size_t(used) * (kBlockBytes / 4), 0);
                }
                const std::uint64_t bit = page & ((1u << 20) - 1);
                blocks[std::size_t(l1[chunk] - 1) * (kBlockBytes / 4) + std::size_t(bit >> 5)] |= 1u << (bit & 31);
            }
        }
        l1_ = std::move(l1);
        blocks_ = std::move(blocks);
        built_version_ = version;
        heap_base_ = heap_base;
        return true;
    }

    // Writes what changed into the mapped table: level 2 first, so a level-1 entry never points at an unwritten block.
    void upload(std::uint8_t* mapped) {
        auto* gpu_l1 = reinterpret_cast<std::uint32_t*>(mapped);
        auto* gpu_blocks = reinterpret_cast<std::uint32_t*>(mapped + kL1Bytes);
        if (shadow_blocks_.size() < blocks_.size()) shadow_blocks_.resize(blocks_.size(), 0);
        for (std::size_t i = 0; i < shadow_blocks_.size(); ++i) {
            const std::uint32_t v = i < blocks_.size() ? blocks_[i] : 0;
            if (shadow_blocks_[i] != v) gpu_blocks[i] = shadow_blocks_[i] = v;
        }
        std::atomic_thread_fence(std::memory_order_release);
        if (shadow_l1_.empty()) shadow_l1_.assign(kL1Entries, 0);
        for (std::uint32_t i = 0; i < kL1Entries; ++i)
            if (shadow_l1_[i] != l1_[i]) gpu_l1[i] = shadow_l1_[i] = l1_[i];
    }

    bool overflowed() const { return overflow_; }
    std::size_t blocks_used() const { return blocks_.size() / (kBlockBytes / 4); }

private:
    std::vector<std::uint32_t> l1_, blocks_, shadow_l1_, shadow_blocks_;
    std::uint64_t built_version_ = 0;
    VkDeviceAddress heap_base_ = 0;
    bool overflow_ = false;
};

// The header the shaders read, written into the arena's mapped memory (magic last).
inline void write_header(std::uint8_t* arena_mapped, std::uint64_t table_offset, std::uint64_t arena_size) {
    auto* h = reinterpret_cast<volatile std::uint32_t*>(arena_mapped + kHeaderOffset);
    h[2] = std::uint32_t(table_offset);
    h[3] = std::uint32_t(table_offset >> 32);
    h[4] = std::uint32_t(arena_size);
    h[5] = std::uint32_t(arena_size >> 32);
    std::atomic_thread_fence(std::memory_order_release);
    h[0] = kMagic;
}

}  // namespace leonida::address_guard
