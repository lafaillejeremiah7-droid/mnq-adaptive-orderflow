(** Historical PRICE-ONLY research replay over one-minute OHLC bars.
    A time gap starts a new warmup segment; no candle is interpolated.
    This reports descriptive regime counts, NOT historical trade outcomes,
    predictive accuracy, or profits. *)

type counts = {
  up : int;
  down : int;
  range : int;
  spike : int;
}

type t = {
  quant : Quant.state;
  last_minute_ms : int64 option;
  bars : int;
  segments : int;
  classified : int;
  segment_bars : int;
  longest_segment : int;
  counts : counts;
}

let empty =
  {
    quant = Quant.empty;
    last_minute_ms = None;
    bars = 0;
    segments = 0;
    classified = 0;
    segment_bars = 0;
    longest_segment = 0;
    counts = { up = 0; down = 0; range = 0; spike = 0 };
  }

let add_regime counts = function
  | Quant.Trending_up -> { counts with up = counts.up + 1 }
  | Quant.Trending_down -> { counts with down = counts.down + 1 }
  | Quant.Ranging -> { counts with range = counts.range + 1 }
  | Quant.Volatility_spike -> { counts with spike = counts.spike + 1 }

let append state (bar : Market.bar) =
  if
    match state.last_minute_ms with
    | Some previous -> Int64.compare bar.minute_start_ms previous <= 0
    | None -> false
  then
    Error "Historical price rows must have strictly increasing minute timestamps"
  else
    let new_segment =
      match state.last_minute_ms with
      | None -> true
      | Some previous ->
          not
            (Int64.equal bar.minute_start_ms (Int64.add previous 60_000L))
    in
    let quant = if new_segment then Quant.empty else state.quant in
    match Quant.on_closed_bar quant bar with
    | Error message -> Error message
    | Ok (quant, measurement) ->
        let segment_bars =
          if new_segment then 1 else state.segment_bars + 1
        in
        let counts, classified =
          match measurement with
          | None -> state.counts, state.classified
          | Some m ->
              add_regime state.counts m.regime, state.classified + 1
        in
        Ok
          {
            quant;
            last_minute_ms = Some bar.minute_start_ms;
            bars = state.bars + 1;
            segments = state.segments + (if new_segment then 1 else 0);
            classified;
            segment_bars;
            longest_segment = max state.longest_segment segment_bars;
            counts;
          }
