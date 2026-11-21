"""Frozen MNQ bar-signal catalog. Run as a script to regenerate catalog.csv.

Rows are chronological U.S. cash sessions. Column j is the completed minute
starting 09:30 ET + j minutes. A signal at j is first actionable at j+1.
All windows are trailing, full, within the same session and include j unless
a lag is shown. No previous contract/session data are required. Missing,
zero-volume or invalid bars are unavailable. A rolling window containing an
unavailable bar is unavailable. Opening anchors require a complete anchor.
A session-cumulative VWAP proxy becomes unavailable after a missing bar.

Signals are directional entry candidates, not fills. The shared replay engine
sets intraday hours, sizing, execution and exits. No formula estimates trade
aggressor, volume-at-price, resting liquidity, true VWAP, or order book depth.
"""
import csv
from pathlib import Path

import numpy as np
import pandas as pd


# Name, family, long/short decision, economic hypothesis, main weakness.
BASES = [
    ("Donchian close breakout", "range breakout",
     "Long if C > lag(max20(H)); short if C < lag(min20(L)).",
     "A close beyond a settled price channel may identify directional repricing.",
     "An isolated breakout may reverse before costs are recovered."),
    ("Inside-bar mother-range release", "range breakout",
     "Bar t-1 lies inside t-2 with a strictly smaller range. Long if C > H[t-2]; short if C < L[t-2].",
     "A locally compressed auction may expand beyond its enclosing bar.",
     "The enclosing bar can be too small for the move to cover costs."),
    ("Nested-box expansion", "range breakout",
     "Previous 8-bar high-low width < 0.65 times the width of the 24 bars immediately before them. Long/short on close above/below the previous 8-bar high/low.",
     "Compression relative to a disjoint earlier range may precede expansion.",
     "A wider earlier range can create mechanical compression during a quiet session."),
    ("Narrowest-of-seven release", "range breakout",
     "The previous positive-range bar ties or sets the smallest high-low range among its last seven. Long/short on close above/below its high/low.",
     "Capital committed after an unusually narrow bar may extend the first break.",
     "Normal one-tick fluctuations can break a narrow range."),
    ("Opening-half-hour acceptance", "opening auction",
     "After 30 complete opening bars, long on the second successive close above their high when the third-most-recent close was at/below that high. Mirror below the opening low.",
     "A second outside close may distinguish sustained repricing from a single excursion.",
     "Waiting for two closes can surrender most of the initial move."),
    ("Opening boundary retest", "opening auction",
     "After the first 30 bars, long when previous close > opening high, current low <= that high and C > it. Mirror at the opening low for shorts.",
     "A previously crossed opening boundary may support entry on a retest.",
     "Repeated boundary tests can precede a complete reversal."),
    ("Opening-drive midpoint recovery", "opening auction",
     "Let U,D be first-15-bar high/low, m=(U+D)/2 and x=C[14]-O[0]. After that interval, long on an upward close cross of m if x>0.5*(U-D). Mirror for a negative drive.",
     "A strong opening displacement may resume after a pullback to the early midpoint.",
     "Opening information can become stale after a news reversal."),
    ("Session-open rejection", "opening auction",
     "Long if previous four closes were strictly above O[0], L<=O[0], C>O[0]. Short if previous four closes were below O[0], H>=O[0], C<O[0].",
     "A rejected retest of the publicly observed cash-session open may preserve the prevailing direction.",
     "The session open is not always an economically important price."),
    ("Failed twenty-bar extreme", "failed auction",
     "Long when L < lag(min20(L)), C > that old low and (2*C-H-L)/(H-L)>1/3. Mirror at old high with close location < -1/3 for shorts.",
     "A new extreme followed by a strong close back inside may precede a reversal.",
     "OHLC cannot establish the order of the extremes or the reason for the reversal."),
    ("Failed breakout follow-through", "failed auction",
     "Short when C[t-1]>max20(H)[t-2], then C falls below that former boundary and below midpoint(H,L)[t-1]. Long on the symmetric failed downside break.",
     "Traders following a failed breakout may unwind when price reenters the old range.",
     "A brief pause can be mistaken for the failure of a genuine trend."),
    ("Median displacement fade", "price reversion",
     "Let m=lag(median20(C)), a=lag(mean14(TR)). Long when C<m-1.5*a and C>O; short when C>m+1.5*a and C<O.",
     "A stopped price excursion relative to a robust local center may partially revert.",
     "The lagged center can be obsolete in a one-sided repricing."),
    ("Bollinger envelope reentry", "price reversion",
     "Let lower/upper=mean20(C) +/- 2*population_sd20(C). Long when the close crosses back above its lower band; short when it crosses back below its upper band.",
     "A return inside an estimated dispersion envelope may indicate a temporary overshoot.",
     "Moving bands can cross a largely stationary price."),
    ("Signed-return balance recovery", "price reversion",
     "p=sum14(max(r,0))/sum14(abs(r)). Long on p crossing upward through 0.30; short on crossing downward through 0.70.",
     "A recovery in the share of positive price movement may identify exhaustion of selling.",
     "A large old return leaving the window can move the ratio without a new impulse."),
    ("Stochastic range rebound", "price reversion",
     "k=(C-min14(L))/(max14(H)-min14(L)). Long when k crosses upward through 0.20; short when it crosses downward through 0.80.",
     "Movement away from a local range edge may signal a return toward its center.",
     "In a strong trend the range edge can migrate with the price."),
    ("Three-step countertrend reversal", "price reversion",
     "After three strictly negative close changes, long if C breaks the previous high. After three strictly positive changes, short if C breaks the previous low.",
     "A forceful reversal after a one-sided sequence may trigger position unwinds.",
     "A short covering bounce can fade without reversing the preceding trend."),
    ("Session volume-weighted mean reclaim", "bar volume and price",
     "A=sum_since_open(V*(H+L+C)/3)/sum_since_open(V). Long on an upward close cross of A with C>O; short on a downward cross with C<O.",
     "Reclaiming a bar-volume-weighted reference may proxy a change in session positioning.",
     "Typical-price bar weighting can differ materially from trade-by-trade VWAP."),
    ("Volume-weighted price premium", "bar volume and price",
     "T=(H+L+C)/3, u=sum20(V*T)/sum20(V)-mean20(T). Long on u crossing above zero; short on u crossing below zero.",
     "A changing premium on high-volume bars may mark a shift in where activity concentrates.",
     "An old high-volume bar leaving the window can flip the premium."),
    ("Close-signed volume persistence", "bar volume and price",
     "s=sum10(V*sign(r))/sum10(V). Long if s>0.50 and C>O; short if s< -0.50 and C<O.",
     "Repeated high-volume bars closing in the same direction may capture price participation.",
     "The close sign does not identify buyer- or seller-initiated volume."),
    ("Volume-climax rejection", "bar volume and price",
     "Require V>2*lag(mean20(V)). Long if lower wick > 0.55*(H-L) and C>O; short on upper-wick mirror and C<O.",
     "Large participation combined with a rejected extreme may mark a transient imbalance.",
     "News releases can produce large wicks followed by another violent move."),
    ("Low-volume pullback recovery", "bar volume and price",
     "V[t-1]<0.60*mean10(V)[t-2]. Long when previous candle was bearish and C>H[t-1]; mirror with previous bullish candle and C<L[t-1].",
     "A reversal of a low-participation pullback may rejoin the earlier path.",
     "Thin activity can also mean spreads are wide and follow-through weak."),
    ("Fast-slow mean crossover", "drift and trend",
     "Long when mean5(C) crosses upward through mean20(C); short on a downward cross.",
     "A short-horizon mean overtaking a slow mean estimates a change in directional drift.",
     "Overlapping moving averages repeatedly cross during low-amplitude noise."),
    ("Regression slope acceleration", "drift and trend",
     "b[k] is OLS slope of C on bar index in window k. Long when b[8]-b[24] crosses above zero with b[24]>0. Mirror below zero with b[24]<0.",
     "Acceleration aligned with an established linear drift may extend.",
     "Least-squares slopes can be dominated by one extreme close."),
    ("Directional-efficiency onset", "drift and trend",
     "e=abs(C-C[t-10])/sum10(abs(r)). On the first cross above 0.60, follow sign(C-C[t-10]).",
     "An efficient path may indicate persistent directional movement after microstructure noise.",
     "A one-off jump produces high efficiency even when following returns are flat."),
    ("Studentized short-run drift", "drift and trend",
     "z=sqrt(12)*mean12(r)/population_sd12(r). Long on a crossing above 1.75, short on a crossing below -1.75. z is a score, not a p-value.",
     "Return drift large relative to recent dispersion may persist over the holding horizon.",
     "Serial dependence and jumps invalidate textbook t-distribution interpretations."),
    ("Directional movement dominance", "drift and trend",
     "u=H-H[t-1], d=L[t-1]-L. p=u if u>0 and u>d, else 0; m=d if d>0 and d>u, else 0. Long/short when sum10(p-m)/sum10(TR) crosses +0.30/-0.30 outward.",
     "One-sided expansion of bar extremes can identify a developing trend.",
     "A single outside bar can distort directional-movement scores."),
    ("Serial continuation", "return dependence",
     "a=sum12(r*lag(r))/sqrt(sum12(r^2)*sum12(lag(r)^2)). When a>0.25, follow the sign of the latest return.",
     "Positive uncentered lag-one return association supports a short continuation hypothesis.",
     "The local association is a noisy estimate and can change sign rapidly."),
    ("Variance-ratio regime switch", "return dependence",
     "v=mean20((C-C[t-5])^2)/(5*mean20(r^2)). Follow sign(C-C[t-5]) for v>1.30; fade it for v<0.70; otherwise stay flat.",
     "The ratio compares multi-minute displacement to one-minute variation to select momentum or reversion.",
     "Overlapping return windows and changing drift can distort the descriptive ratio."),
    ("Realized semivariance imbalance", "return dependence",
     "s=sum18(sign(r)*r^2)/sum18(r^2). Long when s crosses above 0.45, short when s crosses below -0.45.",
     "Asymmetric squared movement measures which direction accounts for recent realized risk.",
     "One jump can dominate the score after any informational advantage has dissipated."),
    ("Directional sign-count onset", "return dependence",
     "s=sum9(sign(r)). Long on a move from s<5 to s>=5; short on a move from s> -5 to s<= -5.",
     "A run of many same-direction moves may be more persistent than a single large jump.",
     "Many small upticks can be offset by a single much larger downtick."),
    ("Two-block V reversal", "return dependence",
     "a=C[t-5]-C[t-10], b=C-C[t-5], q=mean14(TR)[t-5]. Long if a< -q and b> -1.2*a. Short if a>q and b< -1.2*a.",
     "An opposite five-minute displacement that exceeds the preceding leg may signal reversal.",
     "The chosen block endpoints can split a move arbitrarily."),
    ("Long-tail rejection", "candle geometry",
     "Long if lower wick>2*abs(C-O), lower wick>=0.55*(H-L), and L<=lag(min5(L)). Mirror for upper wick and H>=lag(max5(H)).",
     "A rejected local extreme can reveal asymmetric closing-price pressure.",
     "A minute candle hides the exact sequence and executable quotes."),
    ("Body engulfing reversal", "candle geometry",
     "Long when previous C<O, current C>O, O<=C[t-1] and C>=O[t-1]. Mirror for a bearish body engulfing a bullish body.",
     "A candle that reverses the entire preceding body may mark a change in short-run control.",
     "A tiny prior body makes engulfment economically trivial."),
    ("Outside-bar expansion close", "candle geometry",
     "Require H>H[t-1] and L<L[t-1]. Long when C>H[t-1] and close location (2*C-H-L)/(H-L)>0.5; mirror below the prior low and -0.5.",
     "Following an expansion bar in its closing direction may capture a new directional impulse.",
     "An expansion close can occur at the end of an exhausted move."),
    ("Three-candle exhaustion turn", "candle geometry",
     "Bar t-2 has body size>mean14(TR)[t-3]; t-1 body<0.35*that size. Long after a bearish t-2 when current bullish close exceeds its body midpoint; mirror for shorts.",
     "A pause and recovery after a large displacement may indicate exhaustion.",
     "The middle pause can also precede another leg in the original direction."),
    ("Two-sided doji resolution", "candle geometry",
     "Previous bar has positive range, abs(C-O)<=0.20*(H-L), and both wicks>=0.25*(H-L). Follow a close above its high or below its low.",
     "A break of a balanced, two-sided bar may reveal which side gains control.",
     "Doji bars are frequent in quiet periods where costs dominate."),
    ("Completed five-minute staircase", "multiscale structure",
     "A,B are the two most recent completed, fixed five-minute blocks before the current block. If A.low>B.low, long when C>A.high; if A.high<B.high, short when C<A.low.",
     "Short-horizon breakout aligned with a sequence of block extremes may persist.",
     "Clock-based bars can impose artificial structure on a continuous auction."),
    ("Half-hour boundary repricing", "clock and activity",
     "In the first three bars starting at each :00 or :30, require V>1.40*lag(mean10(V)). Follow a close above the previous high or below the previous low.",
     "Concentrated participation around recurring clock boundaries may accelerate repricing.",
     "Scheduled events can produce adverse fills that overwhelm any directional effect."),
    ("Range-extreme recency", "multiscale structure",
     "Long if max3(H)=max20(H), min13(L)>min20(L), and C>H[t-1]. Short if min3(L)=min20(L), max13(H)<max20(H), and C<L[t-1].",
     "Recent highs and older lows describe a rising range without fitting a slope.",
     "A stale extreme mechanically ages out of the window."),
    ("Choppy-range escape", "multiscale structure",
     "j=log(sum14(TR)/(max14(H)-min14(L)))/log(14). If lag(j)>0.60, follow a close above lag(max5(H)) or below lag(min5(L)).",
     "A close escaping a choppy local range can begin a new directional phase.",
     "High choppiness often persists, causing repeated false exits."),
    ("Price and volume-body disagreement", "bar volume and price",
     "b=sum12(V*(C-O)/(H-L))/sum12(V); zero-range bars have body fraction zero. Long if C<C[t-12], b>0.30 and C>O; mirror if C>C[t-12], b< -0.30 and C<O.",
     "A net price decline with volume concentrated in upward candle bodies may precede reversal.",
     "Body direction is a price proxy, with no information about aggressor side."),
]

POLICIES = [
    ("raw", "Enter on the base decision.", "Tests the original direction directly.", "Accepts every noisy base trigger."),
    ("prior_15m_direction", "Keep a base long/short only if the previous completed fixed 15-minute candle closed above/below its open.",
     "Checks alignment against an already settled higher-timeframe move.", "Can discard profitable reversals."),
    ("recent_volume_expansion", "Keep the base signal only if mean(V[t-5:t-1]) > mean(V[t-25:t-6]), with inclusive endpoints.",
     "Favors signals preceded by increasing participation, without using the signal bar's activity.", "Volume can surge as spreads or adverse selection rise."),
    ("preceding_range_contraction", "Keep the base signal only if mean((H-L)[t-5:t-1]) < mean((H-L)[t-25:t-6]), inclusive.",
     "Restricts entries to recent compression relative to a disjoint earlier window.", "Can miss trends that require sustained expansion."),
    ("next_bar_retest", "At t use only the base signal at t-1. For a long require L<=C[t-1] and C>C[t-1]; for a short require H>=C[t-1] and C<C[t-1].",
     "Tests whether a one-bar retest improves entry quality at the cost of one bar of delay.", "Misses runaway moves, and confirmation itself consumes price distance."),
]


def strategy_id(base_index, policy_index):
    return f"Q{base_index * len(POLICIES) + policy_index + 1:03d}"


def write_catalog(path):
    """Write a deterministic, portable definition/rationale for every decision."""
    legend = ("O/H/L/C/V = 1m open/high/low/close/contracts; r=C-lag(C); "
              "TR=max(H-L,abs(H-lag(C)),abs(L-lag(C))) with H-L on the opening bar. "
              "Closed full-session-local trailing windows; lag=1 bar; "
              "wick distances from candle body to high/low; upward cross is prior <= and current >; "
              "downward cross is prior >= and current <. Missing required data means no signal. "
              "Simultaneous long/short means flat.")
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["strategy_id", "base_id", "family", "base_name", "policy",
                         "base_formula", "policy_formula", "economic_hypothesis",
                         "policy_hypothesis", "base_failure_mode", "policy_failure_mode", "notation"])
        for i, (name, family, formula, rationale, weakness) in enumerate(BASES):
            for j, (policy, modifier, p_rationale, p_weakness) in enumerate(POLICIES):
                writer.writerow([strategy_id(i, j), f"B{i+1:02d}", family, name, policy,
                                 formula, modifier, rationale, p_rationale, weakness, p_weakness, legend])


def lag(x, n=1):
    """Shift within each row, using an unavailable leading value."""
    if n <= 0:
        raise ValueError("lag must be positive")
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if n < x.shape[1]:
        out[:, n:] = x[:, :-n]
    return out


def roll(x, n, operation="mean"):
    w = pd.DataFrame(x.T, copy=False).rolling(n, min_periods=n)
    if operation == "sd":
        result = w.std(ddof=0)
    else:
        result = getattr(w, operation)()
    return result.to_numpy(copy=False).T


def ratio(x, y):
    out = np.full(np.broadcast_shapes(np.shape(x), np.shape(y)), np.nan, dtype=np.float64)
    return np.divide(x, y, out=out, where=np.isfinite(y) & (y != 0))


def unsigned_cross_up(x, level):
    distance = x - level
    return (lag(distance) <= 0) & (distance > 0)


def unsigned_cross_down(x, level):
    distance = x - level
    return (lag(distance) >= 0) & (distance < 0)


def directions(up, down):
    # A two-sided, indecisive event is flat. Boolean differences use int8.
    return np.asarray(up, dtype=np.int8) - np.asarray(down, dtype=np.int8)


def direction(x):
    return directions(x > 0, x < 0)


def anchor(x, n, operation):
    """Per-row constant revealed when column n-1 has closed."""
    out = np.full(x.shape, np.nan)
    if x.shape[1] >= n:
        if operation == "first":
            level = x[:, 0]
        elif operation == "last":
            level = x[:, n-1]
        elif operation == "high":
            level = np.max(x[:, :n], axis=1)
        elif operation == "low":
            level = np.min(x[:, :n], axis=1)
        else:
            raise ValueError(operation)
        usable = np.all(np.isfinite(x[:, :n]), axis=1)
        out[:, n-1:] = np.where(usable, level, np.nan)[:, None]
    return out


def settled_block(x, minutes, operation):
    """Broadcast the previous complete clock block to the next block only."""
    out = np.full(x.shape, np.nan)
    for end in range(minutes, x.shape[1], minutes):
        block = x[:, end-minutes:end]
        if operation == "first":
            value = block[:, 0]
        elif operation == "last":
            value = block[:, -1]
        elif operation == "high":
            value = block.max(axis=1)
        elif operation == "low":
            value = block.min(axis=1)
        else:
            raise ValueError(operation)
        value = np.where(np.all(np.isfinite(block), axis=1), value, np.nan)
        out[:, end:min(end+minutes, x.shape[1])] = value[:, None]
    return out


def clean_bars(bars, dates):
    keys = ("open", "high", "low", "close", "volume")
    columns = [np.asarray(bars[k], dtype=np.float64) for k in keys]
    if (columns[0].ndim != 2 or len(dates) != columns[0].shape[0]
            or not 0 < columns[0].shape[1] <= 330 or columns[0].shape[0] == 0
            or any(x.shape != columns[0].shape for x in columns)):
        raise ValueError("expected nonempty, equal session-by-minute arrays, with at most 330 minutes")
    if any(later <= earlier for earlier, later in zip(dates, dates[1:])):
        raise ValueError("session dates must increase strictly")
    o, h, l, c, v = columns
    valid = (np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c) &
             np.isfinite(v) & (l > 0) & (v > 0) & (l <= o) & (o <= h) &
             (l <= c) & (c <= h))
    if not valid.all():
        columns = [np.where(valid, x, np.nan) for x in columns]
    return (*columns, valid)


def base_signals(o, h, l, c, v):
    pc, ph, pl, po = lag(c), lag(h), lag(l), lag(o)
    bar_range = h-l
    r = c-pc
    tr = np.maximum(np.maximum(bar_range, np.abs(h-pc)), np.abs(l-pc))
    tr[:, 0] = bar_range[:, 0]
    a14 = roll(tr, 14)
    body = c-o
    lower = np.minimum(c,o)-l
    upper = h-np.maximum(c,o)
    location = ratio(2*c-h-l, bar_range)
    high20, low20 = roll(h,20,"max"), roll(l,20,"min")
    h20, l20 = lag(high20), lag(low20)

    # B01-B05: channel, inside, relative box, narrow range and opening acceptance.
    yield directions(c > h20, c < l20)
    inside = (ph <= lag(h,2)) & (pl >= lag(l,2)) & (lag(bar_range) < lag(bar_range,2))
    yield directions(inside & (c > lag(h,2)), inside & (c < lag(l,2)))
    h8, l8 = lag(roll(h,8,"max")), lag(roll(l,8,"min"))
    earlier_width = lag(roll(h,24,"max")-roll(l,24,"min"),9)
    box = (h8-l8) < 0.65*earlier_width
    yield directions(box & (c > h8), box & (c < l8))
    nr = (lag(bar_range) > 0) & (lag(bar_range) == lag(roll(bar_range,7,"min")))
    yield directions(nr & (c > ph), nr & (c < pl))
    opening_high, opening_low = anchor(h,30,"high"), anchor(l,30,"low")
    # A third-most-recent close inside the block is permitted, but both
    # confirming closes must come after it. Inclusive mask supports short fixtures.
    after_two = np.arange(c.shape[1]) >= 31
    yield directions(after_two & (c > opening_high) & (pc > opening_high) & (lag(c,2) <= opening_high),
                     after_two & (c < opening_low) & (pc < opening_low) & (lag(c,2) >= opening_low))

    # B06-B10: retests, opening drive, session open and failed breaks.
    after_opening = np.arange(c.shape[1]) >= 30
    yield directions(after_opening & (pc > opening_high) & (l <= opening_high) & (c > opening_high),
                     after_opening & (pc < opening_low) & (h >= opening_low) & (c < opening_low))
    hi15, lo15 = anchor(h,15,"high"), anchor(l,15,"low")
    mid = (hi15+lo15)/2
    move = anchor(c,15,"last")-anchor(o,15,"first")
    yield directions((move > 0.5*(hi15-lo15)) & unsigned_cross_up(c,mid),
                     (move < -0.5*(hi15-lo15)) & unsigned_cross_down(c,mid))
    session_open = o[:, :1]
    yield directions((lag(roll(c,4,"min")) > session_open) & (l <= session_open) & (c > session_open),
                     (lag(roll(c,4,"max")) < session_open) & (h >= session_open) & (c < session_open))
    yield directions((l < l20) & (c > l20) & (location > 1/3),
                     (h > h20) & (c < h20) & (location < -1/3))
    former_h, former_l = lag(h20), lag(l20)
    prior_mid = (ph+pl)/2
    yield directions((pc < former_l) & (c > former_l) & (c > prior_mid),
                     (pc > former_h) & (c < former_h) & (c < prior_mid))

    # B11-B15: return away from an extreme in price, envelope, momentum or range.
    m = lag(roll(c,20,"median"))
    a = lag(a14)
    yield directions((c < m-1.5*a) & (body > 0), (c > m+1.5*a) & (body < 0))
    m20 = roll(c,20)
    sd20 = roll(c,20,"sd")
    yield directions(unsigned_cross_up(c,m20-2*sd20), unsigned_cross_down(c,m20+2*sd20))
    p = ratio(roll(np.maximum(r,0),14,"sum"), roll(np.abs(r),14,"sum"))
    yield directions(unsigned_cross_up(p,0.30), unsigned_cross_down(p,0.70))
    hi14, lo14 = roll(h,14,"max"), roll(l,14,"min")
    k = ratio(c-lo14,hi14-lo14)
    yield directions(unsigned_cross_up(k,0.20), unsigned_cross_down(k,0.80))
    yield directions((lag(roll(r,3,"max")) < 0) & (c > ph), (lag(roll(r,3,"min")) > 0) & (c < pl))

    # B16-B20: bar-derived activity proxies. Actual trade-side labels are absent.
    typical = (h+l+c)/3
    weighted = typical*v
    avg = ratio(np.cumsum(weighted,axis=1),np.cumsum(v,axis=1))
    yield directions(unsigned_cross_up(c,avg) & (body>0), unsigned_cross_down(c,avg) & (body<0))
    premium = ratio(roll(weighted,20,"sum"),roll(v,20,"sum"))-roll(typical,20)
    yield directions(unsigned_cross_up(premium,0),unsigned_cross_down(premium,0))
    signed = ratio(roll(v*np.sign(r),10,"sum"),roll(v,10,"sum"))
    yield directions((signed>0.50)&(body>0),(signed< -0.50)&(body<0))
    high_v = v > 2*lag(roll(v,20))
    yield directions(high_v & (lower>0.55*bar_range) & (body>0),
                     high_v & (upper>0.55*bar_range) & (body<0))
    slow_pullback = lag(v) < 0.60*lag(roll(v,10),2)
    yield directions(slow_pullback & (pc<po) & (c>ph), slow_pullback & (pc>po) & (c<pl))

    # B21-B25: location, slope, directional efficiency, drift and directional movement.
    m5 = roll(c,5)
    yield directions(unsigned_cross_up(m5,m20), unsigned_cross_down(m5,m20))
    idx = np.arange(c.shape[1], dtype=float)
    def slope(n):
        # Cov(time,price) / Var(time) in a full window of n equally spaced observations.
        return (roll(c*idx,n)-roll(c,n)*(idx-(n-1)/2))/((n*n-1)/12)
    b8, b24 = slope(8), slope(24)
    acceleration = b8-b24
    yield directions(unsigned_cross_up(acceleration,0) & (b24>0),
                     unsigned_cross_down(acceleration,0) & (b24<0))
    d10 = c-lag(c,10)
    efficiency = ratio(np.abs(d10),roll(np.abs(r),10,"sum"))
    yield np.where(unsigned_cross_up(efficiency,0.60),direction(d10),0).astype(np.int8)
    z = ratio(np.sqrt(12)*roll(r,12),roll(r,12,"sd"))
    yield directions(unsigned_cross_up(z,1.75), unsigned_cross_down(z,-1.75))
    up, down = h-ph, pl-l
    dm = np.where((up>0)&(up>down), up, 0.0)-np.where((down>0)&(down>up), down, 0.0)
    dm[~np.isfinite(up+down)] = np.nan
    score = ratio(roll(dm,10,"sum"),roll(tr,10,"sum"))
    yield directions(unsigned_cross_up(score,0.30),unsigned_cross_down(score,-0.30))

    # B26-B30: serial association, multihorizon variance and sign/asymmetry.
    pr = lag(r)
    serial = ratio(roll(r*pr,12,"sum"),np.sqrt(roll(r*r,12,"sum")*roll(pr*pr,12,"sum")))
    yield np.where(serial>0.25, direction(r),0).astype(np.int8)
    d5 = c-lag(c,5)
    vr = ratio(roll(d5*d5,20),5*roll(r*r,20))
    yield (direction(d5)*directions(vr>1.30,vr<0.70)).astype(np.int8)
    semivar = ratio(roll(np.sign(r)*r*r,18,"sum"),roll(r*r,18,"sum"))
    yield directions(unsigned_cross_up(semivar,0.45),unsigned_cross_down(semivar,-0.45))
    signs = roll(np.sign(r),9,"sum")
    yield directions((signs>=5)&(lag(signs)<5),(signs<=-5)&(lag(signs)>-5))
    previous_leg = lag(d5,5)
    past_atr = lag(a14,5)
    yield directions((previous_leg< -past_atr)&(d5> -1.2*previous_leg),
                     (previous_leg>past_atr)&(d5< -1.2*previous_leg))

    # B31-B35: economically different OHLC candle events.
    low5, high5 = roll(l,5,"min"), roll(h,5,"max")
    yield directions((lower>2*np.abs(body))&(lower>=0.55*bar_range)&(l<=lag(low5)),
                     (upper>2*np.abs(body))&(upper>=0.55*bar_range)&(h>=lag(high5)))
    yield directions((pc<po)&(body>0)&(o<=pc)&(c>=po), (pc>po)&(body<0)&(o>=pc)&(c<=po))
    outside = (h>ph)&(l<pl)
    yield directions(outside&(c>ph)&(location>0.5),outside&(c<pl)&(location< -0.5))
    impulse = lag(body,2)
    pause = (np.abs(impulse)>lag(a14,3)) & (np.abs(lag(body))<0.35*np.abs(impulse))
    impulse_mid = lag((o+c)/2,2)
    yield directions(pause&(impulse<0)&(body>0)&(c>impulse_mid),
                     pause&(impulse>0)&(body<0)&(c<impulse_mid))
    doji = ((bar_range>0)&(np.abs(body)<=0.20*bar_range)&
            (upper>=0.25*bar_range)&(lower>=0.25*bar_range))
    prev_doji = lag(doji) == 1
    yield directions(prev_doji&(c>ph),prev_doji&(c<pl))

    # B36-B40: clock-defined structure, extreme recency, choppiness and proxy disagreement.
    fixed_h = settled_block(h,5,"high")
    fixed_l = settled_block(l,5,"low")
    yield directions((fixed_l>lag(fixed_l,5))&(c>fixed_h), (fixed_h<lag(fixed_h,5))&(c<fixed_l))
    boundary = (np.arange(c.shape[1])%30 < 3) & (v>1.40*lag(roll(v,10)))
    yield directions(boundary&(c>ph),boundary&(c<pl))
    yield directions((roll(h,3,"max")==high20)&(roll(l,13,"min")>low20)&(c>ph),
                     (roll(l,3,"min")==low20)&(roll(h,13,"max")<high20)&(c<pl))
    path_ratio = ratio(roll(tr,14,"sum"), hi14-lo14)
    chop = np.log(path_ratio, where=path_ratio>0, out=np.full_like(path_ratio,np.nan))/np.log(14)
    yield directions((lag(chop)>0.60)&(c>lag(high5)),(lag(chop)>0.60)&(c<lag(low5)))
    frac = np.where(bar_range==0,0,ratio(body,bar_range))
    score = ratio(roll(v*frac,12,"sum"),roll(v,12,"sum"))
    change = c-lag(c,12)
    yield directions((change<0)&(score>0.30)&(body>0),(change>0)&(score< -0.30)&(body<0))


def iter_signals(bars, dates):
    """Yield (Q001..Q200, signed int8[D,T]) chronologically causal bar-close signals."""
    o, h, l, c, v, valid = clean_bars(bars, dates)
    prior15 = direction(settled_block(c,15,"last")-settled_block(o,15,"first"))
    volume_up = lag(roll(v,5)) > lag(roll(v,20),6)
    bar_range = h-l
    range_down = lag(roll(bar_range,5)) < lag(roll(bar_range,20),6)
    prior_close = lag(c)
    retest_long = (l<=prior_close)&(c>prior_close)
    retest_short = (h>=prior_close)&(c<prior_close)
    count = 0
    for i, raw in enumerate(base_signals(o,h,l,c,v)):
        count += 1
        raw = np.where(valid,raw,0).astype(np.int8)
        yield strategy_id(i,0), raw
        yield strategy_id(i,1), np.where(raw==prior15,raw,0).astype(np.int8)
        yield strategy_id(i,2), np.where(volume_up,raw,0).astype(np.int8)
        yield strategy_id(i,3), np.where(range_down,raw,0).astype(np.int8)
        previous = np.zeros_like(raw)
        previous[:,1:] = raw[:,:-1]
        yield strategy_id(i,4), directions((previous==1)&retest_long,(previous==-1)&retest_short)
    if count != len(BASES):
        raise RuntimeError(f"catalog has {len(BASES)} bases but implementation generated {count}")


if __name__ == "__main__":
    import argparse
    arg = argparse.ArgumentParser(description="Write the 200-strategy MNQ rule catalog.")
    arg.add_argument("output", nargs="?", default=str(Path(__file__).with_name("catalog.csv")))
    write_catalog(arg.parse_args().output)
