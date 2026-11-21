// Optional CPython extension for NQ/MNQ historical trade aggregation.
// This is research-only: NO orders, NO live market connections, NO estimators.
// Preserve the Python reference's integer semantics. Never silently truncate.
#include <pybind11/pybind11.h>
#include <array>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>

namespace py = pybind11;
using i64 = std::int64_t;
using i128 = __int128_t;

struct Counts {
    i64 buy = 0;
    i64 sell = 0;
    i64 unknown = 0;
};

static i64 checked_add(i64 left, i64 right) {
    if (right < 0 || left > std::numeric_limits<i64>::max() - right) {
        throw std::overflow_error("NQ native volume aggregation exceeds signed 64-bit range");
    }
    return left + right;
}

static std::string decimal_i128(i128 value) {
    if (value == 0) return "0";
    bool negative = value < 0;
    // None of the supported, positive market inputs produce negative weights.
    if (negative) throw std::overflow_error("unexpected negative weighted price");
    std::string output;
    while (value > 0) {
        output.push_back(static_cast<char>('0' + value % 10));
        value /= 10;
    }
    std::reverse(output.begin(), output.end());
    return output;
}

static py::tuple aggregate(py::iterable trades) {
    std::unordered_map<i64, i64> price_volume;
    std::unordered_map<i64, Counts> price_sides;
    std::unordered_map<i64, Counts> minute_sides;
    price_volume.reserve(4096);
    price_sides.reserve(4096);
    minute_sides.reserve(1024);

    Counts totals;
    i128 weighted = 0;
    i64 total = 0;
    i64 count = 0;
    for (py::handle trade : trades) {
        const i64 ts = trade.attr("timestamp_ns").cast<i64>();
        const i64 price = trade.attr("price_ticks").cast<i64>();
        const i64 size = trade.attr("size").cast<i64>();
        const std::string side = trade.attr("side").cast<std::string>();
        if (ts < 0 || price <= 0 || size <= 0 || (side != "B" && side != "A" && side != "N")) {
            throw py::value_error("invalid historical trade field for native aggregation");
        }
        total = checked_add(total, size);
        weighted += static_cast<i128>(price) * static_cast<i128>(size);
        price_volume[price] = checked_add(price_volume[price], size);
        Counts &at_price = price_sides[price];
        Counts &at_minute = minute_sides[ts / 60000000000LL];
        if (side == "B") {
            at_price.buy = checked_add(at_price.buy, size);
            at_minute.buy = checked_add(at_minute.buy, size);
            totals.buy = checked_add(totals.buy, size);
        } else if (side == "A") {
            at_price.sell = checked_add(at_price.sell, size);
            at_minute.sell = checked_add(at_minute.sell, size);
            totals.sell = checked_add(totals.sell, size);
        } else {
            at_price.unknown = checked_add(at_price.unknown, size);
            at_minute.unknown = checked_add(at_minute.unknown, size);
            totals.unknown = checked_add(totals.unknown, size);
        }
        count = checked_add(count, 1);
    }
    if (!count) throw py::value_error("profile requires trade events");

    py::dict volume;
    py::dict price;
    py::dict minute;
    for (const auto &[tick, value] : price_volume) {
        volume[py::int_(tick)] = py::int_(value);
    }
    for (const auto &[tick, counts] : price_sides) {
        price[py::int_(tick)] = py::make_tuple(counts.buy, counts.sell, counts.unknown);
    }
    for (const auto &[bucket, counts] : minute_sides) {
        minute[py::int_(bucket)] = py::make_tuple(counts.buy, counts.sell, counts.unknown);
    }
    // Use Python's arbitrary precision integer representation for weighted sums.
    py::object weight = py::module_::import("builtins").attr("int")(decimal_i128(weighted));
    return py::make_tuple(
        volume, price, minute, py::make_tuple(totals.buy, totals.sell, totals.unknown),
        weight, py::int_(total), py::int_(count)
    );
}

PYBIND11_MODULE(_nq_cpp, module) {
    module.doc() = "Optional C++20 batch aggregation for historical NQ/MNQ trades";
    module.def("aggregate", &aggregate, py::arg("trades"),
               "Return volume at tick, side-by-price, side-by-minute, totals, and weighted sum.");
}
