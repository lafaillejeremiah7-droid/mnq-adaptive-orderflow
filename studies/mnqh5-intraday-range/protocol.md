# Does MNQ move farther per minute near the U.S. equity open than at midday?

Compare February 2025 MNQH5 outright bars from the existing pinned archive. This retrospective month has previously been examined. Use the input hash in examples/mnqh5-feb.json. For each observed weekday with all 30 start-stamped bars in both 09:30–10:00 and 12:00–12:30 America/New_York, average high minus low in index points within each window. Exclude and identify observed dates with incomplete pairs. Use no imputation. Treat dates as the units of comparison.

Report the median paired difference (opening mean minus midday mean), the number of dates on which the opening mean was larger, all ties, and each date's paired means. The descriptive hypothesis holds in this sample if the median paired difference is positive. The measure is intraminute range. This study cannot establish price direction, causality, or generalization to other periods.
