// Optional CPython extension for NQ/MNQ historical trade aggregation.
// This is research-only: NO orders, NO live market connections, NO estimators.
// Preserve the Python reference's integer semantics. Never silently truncate.
#include <pybind11/pybind11.h>
#include <algorithm>
#include <array>
#include <cstddef>
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

struct PriceBucket {
    i64 volume = 0;
    Counts sides;
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
    // One price hash table instead of separate volume and aggressor maps.
    std::unordered_map<i64, PriceBucket> prices;
    std::unordered_map<i64, Counts> minute_sides;
    std::size_t hint = 4096;
    if (py::isinstance<py::sequence>(trades)) {
        hint = static_cast<std::size_t>(py::len(trades));
    }
    prices.reserve(std::min<std::size_t>(4096, std::max<std::size_t>(16, hint / 32)));
    minute_sides.reserve(std::min<std::size_t>(1024, std::max<std::size_t>(16, hint / 250)));

    Counts totals;
    i128 weighted = 0;
    i64 total = 0;
    i64 count = 0;
    for (py::handle trade : trades) {
        const i64 ts = trade.attr("timestamp_ns").cast<i64>();
        const i64 price = trade.attr("price_ticks").cast<i64>();
        const i64 size = trade.attr("size").cast<i64>();
        const py::object side_value = trade.attr("side");
        if (!PyUnicode_Check(side_value.ptr()) || PyUnicode_GetLength(side_value.ptr()) != 1) {
            throw py::value_error("native side must be a single B/A/N character");
        }
        const Py_UCS4 side = PyUnicode_ReadChar(side_value.ptr(), 0);
        if (ts < 0 || price <= 0 || size <= 0 || (side != 'B' && side != 'A' && side != 'N')) {
            throw py::value_error("invalid historical trade field for native aggregation");
        }
        total = checked_add(total, size);
        weighted += static_cast<i128>(price) * static_cast<i128>(size);
        PriceBucket &bucket = prices[price];
        bucket.volume = checked_add(bucket.volume, size);
        Counts &at_price = bucket.sides;
        Counts &at_minute = minute_sides[ts / 60000000000LL];
        if (side == 'B') {
            at_price.buy = checked_add(at_price.buy, size);
            at_minute.buy = checked_add(at_minute.buy, size);
            totals.buy = checked_add(totals.buy, size);
        } else if (side == 'A') {
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
    for (const auto &[tick, bucket] : prices) {
        volume[py::int_(tick)] = py::int_(bucket.volume);
        const Counts &counts = bucket.sides;
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
