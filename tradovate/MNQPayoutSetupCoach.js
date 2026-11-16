/* Native Tradovate MNQ setup assistant.
 * Feed: current Tradovate chart (1-minute MNQ bars + d.profile()).
 * No network calls, credentials, order execution, or screen capture.
 * +1 LONG CANDIDATE / -1 SHORT CANDIDATE / 0 NO CANDIDATE.
 * No predictive edge is claimed. "Absorption" is a print-based proxy.
 */
const predef = require("./tools/predef");
const meta = require("./tools/meta");

function etInfo(timestamp) {
    const date = new Date(timestamp);
    if (!Number.isFinite(date.getTime())) return null;
    const fmt = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York", year: "numeric", month: "2-digit",
        day: "2-digit", hour: "2-digit", minute: "2-digit",
        hourCycle: "h23", weekday: "short"
    });
    const fields = {};
    fmt.formatToParts(date).forEach(function (part) {
        fields[part.type] = part.value;
    });
    const hour = Number(fields.hour);
    const minute = Number(fields.minute);
    const day = fields.year + "-" + fields.month + "-" + fields.day;
    return {
        day: day, minute: hour * 60 + minute,
        weekday: fields.weekday, timestamp: date.getTime()
    };
}

function profileOf(source) {
    if (!Array.isArray(source) || source.length === 0) return null;
    const levels = new Map();
    for (const row of source) {
        const price = Number(row.price);
        const ask = Number(row.askVol);
        const bid = Number(row.bidVol);
        const vol = Number(row.vol);
        if (!Number.isFinite(price) || !Number.isFinite(ask) ||
            !Number.isFinite(bid) || !Number.isFinite(vol) ||
            ask < 0 || bid < 0 || vol < 0) return null;
        if (!Number.isInteger(Math.round(price / .25)) ||
            Math.abs(price / .25 - Math.round(price / .25)) > 1e-6) return null;
        if (Math.abs(ask + bid - vol) > Math.max(1, vol * 0.02)) return null;
        const tick = Math.round(price / 0.25);
        const previous = levels.get(tick) || { ask: 0, bid: 0, vol: 0 };
        previous.ask += ask;
        previous.bid += bid;
        previous.vol += vol;
        levels.set(tick, previous);
    }
    return levels.size ? levels : null;
}

function combinedProfile(rows) {
    const result = new Map();
    for (const bar of rows) {
        for (const [tick, value] of bar.profile) {
            result.set(tick, (result.get(tick) || 0) + value.vol);
        }
    }
    return result;
}

function volumeLevels(volumeMap) {
    const points = Array.from(volumeMap.entries()).filter(function (item) {
        return item[1] > 0;
    }).sort(function (a,b) { return a[0] - b[0]; });
    if (!points.length) return null;
    const total = points.reduce(function (s,item) { return s + item[1]; }, 0);
    const center = points.reduce(function (s,item) {
        return s + item[0] * item[1];
    }, 0) / total;
    let poc = 0;
    for (let i = 1; i < points.length; i++) {
        if (points[i][1] > points[poc][1] ||
            (points[i][1] === points[poc][1] &&
             Math.abs(points[i][0] - center) < Math.abs(points[poc][0] - center))) {
            poc = i;
        }
    }
    let lo = poc, hi = poc, captured = points[poc][1];
    while (captured < 0.7 * total && (lo > 0 || hi < points.length - 1)) {
        const left = lo > 0 ? points[lo - 1][1] : -1;
        const right = hi + 1 < points.length ? points[hi + 1][1] : -1;
        if (left >= right) { lo--; captured += left; }
        else { hi++; captured += right; }
    }
    return {
        poc: points[poc][0] * 0.25,
        val: points[lo][0] * 0.25,
        vah: points[hi][0] * 0.25,
        volume: total
    };
}

function median(numbers) {
    const sorted = numbers.slice().sort(function (a,b) { return a-b; });
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid-1]+sorted[mid])/2;
}

function aggregation(rows, timeframe, lastClosedAt) {
    const groups = new Map();
    for (const row of rows) {
        const startMinute = Math.floor(row.minute / timeframe) * timeframe;
        const key = row.day + ":" + startMinute;
        if (startMinute + timeframe > lastClosedAt) continue;
        if (!groups.has(key)) {
            groups.set(key, { day: row.day, minute: startMinute,
                              rows: [], high: row.high, low: row.low, close: row.close,
                              delta: 0 });
        }
        const group = groups.get(key);
        group.rows.push(row);
        group.high = Math.max(group.high, row.high);
        group.low = Math.min(group.low, row.low);
        group.close = row.close;
        group.delta += row.delta;
    }
    return Array.from(groups.values()).filter(function (g) {
        // A 5m/15m group is only usable if every minute was observed.
        return g.rows.length === timeframe;
    });
}

function checkCandidate(rows, active, contract) {
    if (contract && !/^MNQ/i.test(contract)) {
        return { valid: false, reason: "NOT_MNQ_CONTRACT" };
    }
    if (!active || !rows.length) {
        return { valid: false, reason: "AWAITING_COMPLETE_BAR" };
    }
    // Only completed bars may enter the signal. The active bar never enters.
    const completed = rows.filter(function (row) {
        return row.timestamp < active.timestamp && row.day === active.day &&
               row.minute >= 570 && row.minute < 960;
    });
    if (!completed.length || completed[0].minute !== 570) {
        return { valid: false, reason: "INCOMPLETE_RTH_HISTORY" };
    }
    const last = completed[completed.length - 1];
    if (last.minute < 600 || last.minute >= 900 ||
        ["Mon","Tue","Wed","Thu"].indexOf(last.weekday) === -1) {
        return { valid: true, signal: 0, reason: "OUTSIDE_PERSONAL_WINDOW" };
    }
    // Reject a missing minute, rather than silently filling gaps.
    for (let i=1;i<completed.length;i++) {
        if (completed[i].minute !== completed[i-1].minute+1) {
            return { valid: false, reason: "MISSING_RTH_MINUTES" };
        }
    }
    const recent = completed.slice(-21,-1);
    if (recent.length < 10) {
        return { valid: false, reason: "INSUFFICIENT_BASELINE" };
    }
    const lastEnd = last.minute + 1;
    const fives = aggregation(completed, 5, lastEnd);
    const fifteens = aggregation(completed, 15, lastEnd);
    if (!fives.length || fifteens.length < 2) {
        return { valid: false, reason: "WARMING_UP_5M_15M" };
    }
    const f5 = fives[fives.length-1];
    const f15 = fifteens[fifteens.length-1];
    const older15 = fifteens[fifteens.length-2];
    const bias = f15.close > older15.close ? "up" :
                 f15.close < older15.close ? "down" : "neutral";
    const earlier = completed.slice(0,-1);
    const precedingProfile = volumeLevels(combinedProfile(earlier));
    const p5 = volumeLevels(combinedProfile(f5.rows));
    const p15 = volumeLevels(combinedProfile(f15.rows));
    if (!precedingProfile || !p5 || !p15) {
        return {valid: false, reason: "MISSING_PROFILE"};
    }
    const levels = [];
    [precedingProfile,p5,p15].forEach(function (p) {
        ["poc","val","vah"].forEach(function (name) { levels.push(p[name]); });
    });
    const toleranceTicks = Math.max(4,Math.min(16,
        Math.floor(median(recent.map(function (r) {return (r.high-r.low)/0.25;})) / 4)));
    const near = levels.some(function (value) {
        return Math.abs(value-last.close) <= toleranceTicks * 0.25;
    });
    const lows = recent.map(function (bar) {
        const p = bar.profile.get(Math.round(bar.low/0.25));
        return p ? p.bid : 0;
    });
    const highs = recent.map(function (bar) {
        const p = bar.profile.get(Math.round(bar.high/0.25));
        return p ? p.ask : 0;
    });
    const low = last.profile.get(Math.round(last.low/0.25));
    const high = last.profile.get(Math.round(last.high/0.25));
    const range = last.high-last.low;
    const bullishProxy = range >= .5 && last.delta < 0 &&
        low && low.bid >= Math.max(5, 1.8*median(lows)) &&
        (last.close-last.low)/range >= .6;
    const bearishProxy = range >= .5 && last.delta > 0 &&
        high && high.ask >= Math.max(5, 1.8*median(highs)) &&
        (last.high-last.close)/range >= .6;
    const signal = near && bias === "up" && f5.delta > 0 && bullishProxy ? 1 :
                   near && bias === "down" && f5.delta < 0 && bearishProxy ? -1 : 0;
    return {
        valid: true, signal: signal,
        reason: signal ? "UNVALIDATED_ORDERFLOW_CANDIDATE" : "NO_MATCH",
        bias: bias, delta5: f5.delta,
        delta1: last.delta,
        cvd: completed.reduce(function (s,r) {return s+r.delta;},0),
        poc: precedingProfile.poc, vah: precedingProfile.vah, val: precedingProfile.val
    };
}

class MNQCoach {
    init() {
        this.bars = new Map();
        this.last = null;
    }

    map(d, i) {
        const stamp = etInfo(d.timestamp());
        if (!stamp) return undefined;
        // The requirement asks Tradovate for the same volume-by-price history
        // used by its native footprint tools. Do not substitute OHLCV guesses.
        const chartLevels = typeof d.profile === "function" ? profileOf(d.profile()) : null;
        const ask = Number(d.offerVolume());
        const bid = Number(d.bidVolume());
        const o = Number(d.open()), h = Number(d.high()),
              l = Number(d.low()), c = Number(d.close());
        if (!chartLevels || ![ask,bid,o,h,l,c].every(Number.isFinite) ||
            ask < 0 || bid < 0 || h < l) return undefined;
        const row = Object.assign({}, stamp, {
            open: o, high: h, low: l, close: c, delta: ask-bid,
            profile: chartLevels
        });
        this.bars.set(i,row); // Replace live bar updates; no double counting.
        if (this.bars.size > 1100) {
            const oldest = this.bars.keys().next().value;
            this.bars.delete(oldest);
        }
        if (!d.isLast()) return undefined;
        const sorted = Array.from(this.bars.entries()).sort(function (a,b) {
            return a[0]-b[0];
        }).map(function (item) {return item[1];});
        const active = sorted[sorted.length-1];
        const result = checkCandidate(
            sorted.slice(0,-1), active,
            this.contractInfo && this.contractInfo.product
        );
        this.last = result;
        if (!result.valid) return undefined; // Incomplete data -> no displayed recommendation.
        return {
            value: result.signal,
            style: {
                value: { color: result.signal === 1 ? "#3ac58d" :
                                result.signal === -1 ? "#f07373" : "#94a3b8" }
            }
        };
    }
}

module.exports = {
    name: "MNQPayoutSetupCoach",
    title: "MNQ Setup Coach (Research Only)",
    description: "Automatic MNQ 1m profile/delta and 5m/15m confirmation. +1/-1 unvalidated candidates; no orders.",
    calculator: MNQCoach,
    inputType: meta.InputType.BARS,
    areaChoice: meta.AreaChoice.NEW,
    requirements: {volumeProfiles: true},
    plots: {value: "Candidate +1 / -1"},
    tags: ["My Indicators"],
    schemeStyles: predef.styles.solidLine("#94a3b8")
};
// Exposed to Node-only unit tests by accessing calculator/helpers via vm sandbox.
