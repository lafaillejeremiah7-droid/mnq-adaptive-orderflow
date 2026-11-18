(** Conservative, completed-minute first-touch labeling for research.
    Entry is HYPOTHETIC and assumed filled at [entry_ticks] at the start
    of [detected_at_ms]; this module does not simulate real executions. *)

let label ~regime ~direction ~detected_at_ms ~entry_ticks ~stop_ticks
    ~target_ticks ~horizon_bars ~(future_bars : Market.bar list) =
  if Int64.compare detected_at_ms 0L < 0
     || Int64.rem detected_at_ms 60_000L <> 0L
     || entry_ticks <= 0 || stop_ticks <= 0 || target_ticks <= 0
     || entry_ticks > 1_000_000 || stop_ticks > 1_000_000
     || target_ticks > 1_000_000 || horizon_bars < 1
     || horizon_bars > 500 then
    Error "Invalid event geometry or labeling horizon"
  else
    let geometry_valid =
      match direction with
      | Risk.Long -> stop_ticks < entry_ticks && entry_ticks < target_ticks
      | Risk.Short -> target_ticks < entry_ticks && entry_ticks < stop_ticks
    in
    if not geometry_valid then
      Error "Stop and target must be on opposite sides of entry"
    else
      let target_distance_ticks = abs (target_ticks - entry_ticks) in
      let stop_distance_ticks = abs (stop_ticks - entry_ticks) in
      let outcome resolved_at_ms result =
        Some
          {
            Quant.detected_at_ms;
            resolved_at_ms;
            regime;
            direction;
            target_distance_ticks;
            stop_distance_ticks;
            horizon_bars;
            outcome = result;
          }
      in
      let rec scan count expected = function
        | _ when count >= horizon_bars -> Ok None
        | [] -> Ok None
        | bar :: rest ->
            if not (Int64.equal bar.Market.minute_start_ms expected) then
              Error "Missing, repeated, or out-of-order future minute bar"
            else if bar.open_ticks <= 0 || bar.low_ticks <= 0
                    || bar.high_ticks <= 0 || bar.close_ticks <= 0
                    || bar.low_ticks > bar.high_ticks
                    || bar.open_ticks < bar.low_ticks
                    || bar.open_ticks > bar.high_ticks
                    || bar.close_ticks < bar.low_ticks
                    || bar.close_ticks > bar.high_ticks
                    || bar.buy_volume < 0 || bar.sell_volume < 0 then
              Error "Invalid future OHLCV bar"
            else
              let target_hit, stop_hit =
                match direction with
                | Risk.Long ->
                    ( bar.high_ticks >= target_ticks,
                      bar.low_ticks <= stop_ticks )
                | Risk.Short ->
                    ( bar.low_ticks <= target_ticks,
                      bar.high_ticks >= stop_ticks )
              in
              let resolved_at_ms = Int64.add expected 60_000L in
              if target_hit && stop_hit then
                Error
                  "Both levels touched within one minute: trade-print ordering required"
              else if target_hit then
                Ok (outcome resolved_at_ms Quant.Target_first)
              else if stop_hit then
                Ok (outcome resolved_at_ms Quant.Stop_first)
              else if count + 1 = horizon_bars then
                (* Timed out: count as non-target, not a profitable exit.
                   A time-exit P/L needs a separate backtest. *)
                Ok (outcome resolved_at_ms Quant.Time_limit)
              else scan (count + 1) resolved_at_ms rest
      in
      scan 0 detected_at_ms future_bars
