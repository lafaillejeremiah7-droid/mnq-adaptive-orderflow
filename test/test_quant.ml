open Mnq_core

let now = 10_000_000L

let expect condition message = if not condition then failwith message

let make_bar minute close range =
  {
    Market.minute_start_ms = Int64.mul (Int64.of_int minute) 60_000L;
    open_ticks = close;
    high_ticks = close + range;
    low_ticks = close - range;
    close_ticks = close;
    buy_volume = 20;
    sell_volume = 10;
  }

let update state bar =
  match Quant.on_closed_bar state bar with
  | Ok value -> value
  | Error message -> failwith message

let trend_measurement () =
  let rec run n state observed =
    if n = 25 then
      match observed with
      | Some result -> result
      | None -> failwith "Expected a measurement after warmup"
    else
      let next, result = update state (make_bar (141 + n) (80000 + (2 * n)) 1) in
      if n < 20 then
        expect (result = None) "Quant model must require 21 closed bars";
      run (n + 1) next result
  in
  run 0 Quant.empty None

let test_regimes () =
  let trend = trend_measurement () in
  expect
    (trend.regime = Quant.Trending_up)
    "Monotone rising closes should be trend-up";
  expect
    (trend.efficiency_ratio > 0.99)
    "Directional efficiency calculation is wrong";
  let stable_state, _ =
    List.fold_left
      (fun (state, _) i ->
        update state (make_bar i 80000 1))
      (Quant.empty, None) (List.init 21 Fun.id)
  in
  let _, spiked = update stable_state (make_bar 21 80000 100) in
  expect
    (match spiked with
    | Some m -> m.regime = Quant.Volatility_spike
    | None -> false)
    "True-range spike must be detected";
  expect
    (match
       Quant.on_closed_bar stable_state (make_bar 23 80000 1)
     with
    | Error _ -> true
    | Ok _ -> false)
    "Quant features must fail closed on missing minute";
  expect
    (match
       Quant.on_closed_bar stable_state (make_bar 20 80000 1)
     with
    | Error _ -> true
    | Ok _ -> false)
    "Quant features must reject duplicate or stale minute";
  let alternating =
    List.fold_left
      (fun (state, _) i ->
        update state (make_bar i (80000 + (if i mod 2 = 0 then 1 else -1)) 2))
      (Quant.empty, None) (List.init 25 Fun.id)
  in
  expect
    (match snd alternating with
    | Some m -> m.regime = Quant.Ranging
    | None -> false)
    "Oscillating closes should classify as range"

let account =
  {
    Risk.observed_at_ms = now;
    equity_cents = 5_000_000L;
    drawdown_floor_cents = 4_880_000L;
    day_net_cents = 0L;
    trades_today = 0;
    consecutive_losses = 0;
    open_contracts = 0;
  }

let proposal =
  {
    Risk.direction = Risk.Long;
    entry_ticks = 80050;
    stop_ticks = 80010;
    contracts = 2;
  }

let signal = Some { Risk.direction = Risk.Long; observed_at_ms = now }

let example i outcome =
  {
    Quant.detected_at_ms = Int64.mul (Int64.of_int i) 60_000L;
    resolved_at_ms =
      Int64.add (Int64.mul (Int64.of_int i) 60_000L) 10_000L;
    regime = Quant.Trending_up;
    direction = Risk.Long;
    target_distance_ticks = 80;
    stop_distance_ticks = 40;
    horizon_bars = 10;
    outcome;
  }

let examples wins =
  List.init 100 (fun i ->
      example i
        (if i < wins then Quant.Target_first else Quant.Stop_first))

let review ?(account = account) ?(proposal = proposal)
    ?(measurement = Some (trend_measurement ())) ?(examples = []) () =
  Quant.review ~now_ms:now ~session_open:true ~feed_healthy:true
    ~signal ~account ~proposal ~limits:Risk.default_limits ~measurement
    ~examples ~min_samples:100 ~target_ticks:80130 ~horizon_bars:10

let test_evidence () =
  let measurement = trend_measurement () in
  let history = examples 65 in
  let estimate =
    match
      Quant.estimate ~as_of_ms:now ~min_samples:100
        ~regime:measurement.regime ~direction:Risk.Long
        ~target_distance_ticks:80 ~stop_distance_ticks:40 ~horizon_bars:10 history
    with
    | None -> failwith "Expected historical estimate"
    | Some value -> value
  in
  expect (estimate.samples = 100) "Historical sample count wrong";
  expect (estimate.targets_first = 65) "Historical wins wrong";
  expect
    (estimate.conservative_rate < estimate.historical_rate)
    "Lower confidence bound must be below observed hit rate";
  let future =
    { (example 99 Quant.Target_first) with resolved_at_ms = now }
  in
  expect
    (Quant.estimate ~as_of_ms:now ~min_samples:100
       ~regime:Quant.Trending_up ~direction:Risk.Long
       ~target_distance_ticks:80 ~stop_distance_ticks:40 ~horizon_bars:10
       (future :: List.init 99 (fun i -> example i Quant.Target_first))
     = None)
    "Outcomes resolved at/after decision time must not leak";
  expect
    (Quant.estimate ~as_of_ms:now ~min_samples:100
       ~regime:Quant.Trending_up ~direction:Risk.Long
       ~target_distance_ticks:100 ~stop_distance_ticks:40 ~horizon_bars:10 history = None)
    "Historical examples with different target geometry must be excluded";
  expect
    (Quant.estimate ~as_of_ms:now ~min_samples:100
       ~regime:Quant.Trending_up ~direction:Risk.Long
       ~target_distance_ticks:80 ~stop_distance_ticks:40 ~horizon_bars:20
       history = None)
    "Different vertical horizons must be excluded";
  expect
    (match review () with Quant.Wait _ -> true | _ -> false)
    "No training evidence must abstain";
  expect
    (match review ~examples:history () with
    | Quant.Review_only r ->
        r.conservative_expected_value_cents > 0.0
        && r.sample_count = 100
    | Quant.Wait _ -> false)
    "Positive conditional expectancy should be research-review-only";
  expect
    (match review ~examples:(examples 20) () with
    | Quant.Wait _ -> true
    | _ -> false)
    "Poor historical win rate must abstain";
  expect
    (match
       review ~account:{ account with trades_today = 2 }
         ~examples:history ()
     with
    | Quant.Wait _ -> true
    | _ -> false)
    "Broker-state risk gate must take precedence";
  expect
    (match review ~measurement:None ~examples:history () with
    | Quant.Wait _ -> true
    | _ -> false)
    "Missing regime must abstain";
  let stale =
    match Some (trend_measurement ()) with
    | Some m -> { m with closed_minute_start_ms = 0L }
    | None -> failwith "Unreachable"
  in
  expect
    (match review ~measurement:(Some stale) ~examples:history () with
    | Quant.Wait _ -> true
    | _ -> false)
    "Stale regime measurements must abstain";
  expect
    (match
       review
         ~proposal:{ proposal with stop_ticks = 79900 }
         ~examples:history ()
     with
    | Quant.Wait _ -> true
    | _ -> false)
    "Excessive proposed risk must abstain"

let () =
  test_regimes ();
  test_evidence ();
  print_endline "All quantitative research tests passed."
