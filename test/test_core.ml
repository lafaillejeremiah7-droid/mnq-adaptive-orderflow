open Mnq_core

let expect condition message = if not condition then failwith message

let unwrap = function
  | Ok value -> value
  | Error _ -> failwith "Unexpected market validation error"

let print ~minute ~offset ~price ~quantity ~aggressor =
  {
    Market.timestamp_ms =
      Int64.add (Int64.mul (Int64.of_int minute) 60_000L)
        (Int64.of_int offset);
    price_ticks = price;
    quantity;
    aggressor;
  }

let test_market_and_features () =
  let first =
    print ~minute:100 ~offset:0 ~price:80000 ~quantity:5
      ~aggressor:Market.Buyer
  in
  let second =
    print ~minute:100 ~offset:100 ~price:80001 ~quantity:2
      ~aggressor:Market.Seller
  in
  let next =
    print ~minute:101 ~offset:0 ~price:80002 ~quantity:7
      ~aggressor:Market.Buyer
  in
  let s1, snap1 = unwrap (Features.on_trade Features.empty first) in
  expect (snap1 = None) "First print must not close a bar";
  let s2, snap2 = unwrap (Features.on_trade s1 second) in
  expect (snap2 = None) "Same minute must not close a bar";
  let s3, snap3 = unwrap (Features.on_trade s2 next) in
  let snap =
    match snap3 with Some value -> value | None -> failwith "Expected bar"
  in
  expect (snap.closed_bar.Market.close_ticks = 80001) "Wrong closed bar";
  expect (Market.delta snap.closed_bar = 3) "Wrong bar delta";
  expect (snap.cumulative_delta_since_start = 3) "Future-print CVD leakage";
  expect (s3.cumulative_delta = 10) "New print missing from live CVD";
  expect
    (snap.completed_minute_profile <> None)
    "Missing completed-minute volume profile";
  let missing =
    print ~minute:103 ~offset:0 ~price:80000 ~quantity:1
      ~aggressor:Market.Buyer
  in
  expect
    (match Features.on_trade s3 missing with
    | Error Market.Missing_minute -> true
    | _ -> false)
    "Missing minute must fail closed";
  let old =
    print ~minute:100 ~offset:0 ~price:80000 ~quantity:1
      ~aggressor:Market.Buyer
  in
  expect
    (match Features.on_trade s3 old with
    | Error Market.Out_of_order -> true
    | _ -> false)
    "Out-of-order prints must fail closed"

let test_profile () =
  let make price quantity aggressor =
    print ~minute:1 ~offset:0 ~price ~quantity ~aggressor
  in
  let profile =
    Profile.empty
    |> fun p -> Profile.add_trade p (make 100 5 Market.Buyer)
    |> fun p -> Profile.add_trade p (make 101 3 Market.Seller)
    |> fun p -> Profile.add_trade p (make 102 2 Market.Buyer)
  in
  expect (Profile.delta profile = 4) "Incorrect signed delta";
  let area =
    match Profile.value_area profile with
    | None -> failwith "Expected volume area"
    | Some value -> value
  in
  expect (area.poc_ticks = 100) "Incorrect POC";
  expect (area.val_ticks = 100 && area.vah_ticks = 101) "Incorrect VA";
  expect (area.total_volume = 10) "Incorrect total volume"

let now = 1_000_000L

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
    entry_ticks = 80000;
    stop_ticks = 79960;
    contracts = 2;
  }

let signal = Some { Risk.direction = Risk.Long; observed_at_ms = now }

let evaluate ?(account = account) ?(proposal = proposal)
    ?(signal = signal) ?(feed_healthy = true) () =
  Risk.check ~now_ms:now ~session_open:true ~feed_healthy ~signal
    ~account ~proposal ~limits:Risk.default_limits

let blocked = function Risk.Blocked _ -> true | _ -> false

let test_risk () =
  expect
    (match evaluate () with Risk.Review_only _ -> true | _ -> false)
    "Low-risk proposal should be review-only";
  expect
    (blocked (evaluate ~account:{ account with trades_today = 2 } ()))
    "Third daily trade must be blocked";
  expect
    (blocked (evaluate ~account:{ account with consecutive_losses = 2 } ()))
    "Two losses must block";
  expect
    (blocked (evaluate ~account:{ account with open_contracts = 1 } ()))
    "Existing position must block";
  expect
    (blocked (evaluate ~account:{ account with observed_at_ms = 0L } ()))
    "Stale broker state must block";
  expect
    (blocked (evaluate ~account:{ account with equity_cents = 4_890_000L } ()))
    "Insufficient drawdown headroom must block";
  expect
    (blocked (evaluate ~proposal:{ proposal with stop_ticks = 79880 } ()))
    "Over-budget trade must block";
  expect
    (blocked (evaluate ~proposal:{ proposal with stop_ticks = 80020 } ()))
    "Stop on wrong side must block";
  expect (blocked (evaluate ~signal:None ())) "No signal must block";
  expect
    (blocked
       (evaluate
          ~signal:(Some { Risk.direction = Risk.Short; observed_at_ms = now })
          ()))
    "Mismatched direction must block";
  expect
    (blocked (evaluate ~feed_healthy:false ()))
    "Unhealthy feed must block"

let () =
  test_market_and_features ();
  test_profile ();
  test_risk ();
  print_endline "All OCaml core tests passed."
