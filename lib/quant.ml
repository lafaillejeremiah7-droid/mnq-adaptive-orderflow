(** Research-only quantitative filters for completed MNQ minute bars.
    No live feed, order execution, or trained predictive model is implied. *)

type regime = Trending_up | Trending_down | Ranging | Volatility_spike

type measurement = {
  closed_minute_start_ms : int64;
  regime : regime;
  fast_true_range_ticks : float;
  slow_true_range_ticks : float;
  efficiency_ratio : float;
  closed_bars : int;
}

type state = {
  last_minute_ms : int64 option;
  last_close_ticks : int option;
  recent_closes : int list;
  count : int;
  fast_ewma : float option;
  slow_ewma : float option;
}

let empty =
  {
    last_minute_ms = None;
    last_close_ticks = None;
    recent_closes = [];
    count = 0;
    fast_ewma = None;
    slow_ewma = None;
  }

let rec take n values =
  if n <= 0 then []
  else
    match values with
    | [] -> []
    | first :: rest -> first :: take (n - 1) rest

let rec total_path = function
  | a :: (b :: _ as tail) -> abs (a - b) + total_path tail
  | _ -> 0

let smoothed ~period previous observed =
  match previous with
  | None -> observed
  | Some prior ->
      let alpha = 2.0 /. float_of_int (period + 1) in
      (alpha *. observed) +. ((1.0 -. alpha) *. prior)

(** Requires contiguous, uniquely timestamped, completed minute bars.
    21 closes are needed for a 20-move efficiency ratio. *)
let on_closed_bar state (bar : Market.bar) =
  if Int64.compare bar.minute_start_ms 0L < 0
     || bar.open_ticks <= 0 || bar.high_ticks <= 0
     || bar.low_ticks <= 0 || bar.close_ticks <= 0
     || bar.low_ticks > bar.high_ticks
     || bar.open_ticks < bar.low_ticks || bar.open_ticks > bar.high_ticks
     || bar.close_ticks < bar.low_ticks || bar.close_ticks > bar.high_ticks
     || bar.buy_volume < 0 || bar.sell_volume < 0 then
    Error "Invalid completed OHLCV bar"
  else
    match state.last_minute_ms with
    | Some previous
      when not
             (Int64.equal bar.minute_start_ms
                (Int64.add previous 60_000L)) ->
        Error "Nonconsecutive minute bar; reset and backfill before using quant features"
    | _ ->
        let raw_range = bar.high_ticks - bar.low_ticks in
        let true_range =
          match state.last_close_ticks with
          | None -> raw_range
          | Some previous_close ->
              max raw_range
                (max
                   (abs (bar.high_ticks - previous_close))
                   (abs (bar.low_ticks - previous_close)))
        in
        let observation = float_of_int true_range in
        let fast = smoothed ~period:5 state.fast_ewma observation in
        let slow = smoothed ~period:20 state.slow_ewma observation in
        let closes = take 21 (bar.close_ticks :: state.recent_closes) in
        let count = state.count + 1 in
        let next =
          {
            last_minute_ms = Some bar.minute_start_ms;
            last_close_ticks = Some bar.close_ticks;
            recent_closes = closes;
            count;
            fast_ewma = Some fast;
            slow_ewma = Some slow;
          }
        in
        if count < 21 then Ok (next, None)
        else
          let newest = List.hd closes in
          let oldest = List.nth closes 20 in
          let path = total_path closes in
          let efficiency =
            if path = 0 then 0.0
            else float_of_int (abs (newest - oldest)) /. float_of_int path
          in
          let regime =
            if slow > 0.0 && fast /. slow >= 1.8 then Volatility_spike
            else if efficiency >= 0.55 && newest > oldest then Trending_up
            else if efficiency >= 0.55 && newest < oldest then Trending_down
            else Ranging
          in
          Ok
            ( next,
              Some
                {
                  closed_minute_start_ms = bar.minute_start_ms;
                  regime;
                  fast_true_range_ticks = fast;
                  slow_true_range_ticks = slow;
                  efficiency_ratio = efficiency;
                  closed_bars = count;
                } )

(** An outcome must have actually resolved BEFORE the decision timestamp.
    Out-of-order future results are excluded, never backfilled into a prior
    forecast. All records must correspond to one predeclared stop/target rule. *)
type outcome = Target_first | Stop_first | Time_limit

type resolved_example = {
  detected_at_ms : int64;
  resolved_at_ms : int64;
  regime : regime;
  direction : Risk.direction;
  target_distance_ticks : int;
  stop_distance_ticks : int;
  horizon_bars : int;
  outcome : outcome;
}

type estimate = {
  samples : int;
  targets_first : int;
  historical_rate : float;
  conservative_rate : float;
}

let estimate ~as_of_ms ~min_samples ~regime ~direction
    ~target_distance_ticks ~stop_distance_ticks ~horizon_bars examples =
  if min_samples < 1 || target_distance_ticks < 1
     || stop_distance_ticks < 1 || horizon_bars < 1 || Int64.compare as_of_ms 0L < 0 then None
  else
    let samples, targets =
      List.fold_left
        (fun (n, wins) example ->
          if example.regime <> regime || example.direction <> direction
             || example.target_distance_ticks <> target_distance_ticks
             || example.stop_distance_ticks <> stop_distance_ticks
             || example.horizon_bars <> horizon_bars
             || Int64.compare example.detected_at_ms 0L < 0
             || Int64.compare example.resolved_at_ms example.detected_at_ms < 0
             || Int64.compare example.resolved_at_ms as_of_ms >= 0 then
            (n, wins)
          else
            ( n + 1,
              wins + (if example.outcome = Target_first then 1 else 0) ))
        (0, 0) examples
    in
    if samples < min_samples then None
    else
      let n = float_of_int samples in
      let p = float_of_int targets /. n in
      (* One-sided 95% Wilson lower confidence bound. This is NOT proof
         of calibration or of future profitability. *)
      let z = 1.6448536269514722 in
      let z2 = z *. z in
      let denominator = 1.0 +. (z2 /. n) in
      let center = p +. (z2 /. (2.0 *. n)) in
      let margin =
        z *. sqrt (((p *. (1.0 -. p)) /. n) +. (z2 /. (4.0 *. n *. n)))
      in
      Some
        {
          samples;
          targets_first = targets;
          historical_rate = p;
          conservative_rate = max 0.0 ((center -. margin) /. denominator);
        }

type verdict =
  | Wait of string list
  | Review_only of {
      regime : regime;
      sample_count : int;
      historical_target_rate : float;
      wilson_lower_rate : float;
      estimated_win_cents : int64;
      estimated_loss_cents : int64;
      conservative_expected_value_cents : float;
    }

(** Combines the existing broker-state risk gate with conservative historical
    evidence. A positive result is advisory, NOT an executable order. *)
let review ~now_ms ~session_open ~feed_healthy ~signal ~account ~proposal
    ~limits ~measurement ~examples ~min_samples ~target_ticks ~horizon_bars =
  match
    Risk.check ~now_ms ~session_open ~feed_healthy ~signal ~account
      ~proposal ~limits
  with
  | Risk.Blocked reasons -> Wait reasons
  | Risk.Review_only { estimated_loss_cents; _ } -> (
      match measurement with
      | None -> Wait [ "Insufficient completed bars for regime classification" ]
      | Some observed ->
          let closed_at_ms =
            Int64.add observed.closed_minute_start_ms 60_000L
          in
          let age_ms = Int64.sub now_ms closed_at_ms in
          if Int64.compare age_ms 0L < 0
             || Int64.compare age_ms 120_000L > 0 then
            Wait [ "Quant regime is future-dated or older than 120 seconds" ]
          else if observed.regime = Volatility_spike then
            Wait [ "Volatility spike: experimental model abstains" ]
          else
            let target_valid =
              target_ticks > 0 && target_ticks <= 1_000_000
              &&
              (match proposal.Risk.direction with
              | Risk.Long -> target_ticks > proposal.entry_ticks
              | Risk.Short -> target_ticks < proposal.entry_ticks)
            in
            if not target_valid then Wait [ "Target must be beyond entry in trade direction" ]
            else
              let target_distance_ticks =
                abs (target_ticks - proposal.entry_ticks)
              in
              let stop_distance_ticks =
                abs (proposal.stop_ticks - proposal.entry_ticks)
              in
              match
                estimate ~as_of_ms:now_ms ~min_samples
                  ~regime:observed.regime ~direction:proposal.direction
                  ~target_distance_ticks ~stop_distance_ticks ~horizon_bars examples
              with
              | None ->
                  Wait
                    [
                      "Insufficient resolved, prior, same-regime/side historical examples";
                    ]
              | Some evidence ->
                  let contracts = Int64.of_int proposal.contracts in
                  let ticks =
                    Int64.abs
                      (Int64.sub (Int64.of_int target_ticks)
                         (Int64.of_int proposal.entry_ticks))
                  in
                  let gross_win =
                    Int64.mul ticks (Int64.mul contracts 50L)
                  in
                  let assumed_cost =
                    Int64.mul contracts
                      (Int64.add limits.round_trip_cost_cents_per_contract
                         (Int64.mul
                            (Int64.of_int limits.slippage_ticks)
                            50L))
                  in
                  let net_win = Int64.sub gross_win assumed_cost in
                  if Int64.compare net_win 0L <= 0 then
                    Wait [ "Target reward does not exceed assumed trading costs" ]
                  else
                    let p = evidence.conservative_rate in
                    let ev =
                      (p *. Int64.to_float net_win)
                      -. ((1.0 -. p) *. Int64.to_float estimated_loss_cents)
                    in
                    if ev <= 0.0 then
                      Wait [ "Conservative estimated expected value is not positive" ]
                    else
                      Review_only
                        {
                          regime = observed.regime;
                          sample_count = evidence.samples;
                          historical_target_rate = evidence.historical_rate;
                          wilson_lower_rate = p;
                          estimated_win_cents = net_win;
                          estimated_loss_cents;
                          conservative_expected_value_cents = ev;
                        })
