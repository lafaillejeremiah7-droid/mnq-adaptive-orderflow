open Mnq_core

let expect ok message = if not ok then failwith message
let minute n = Int64.mul (Int64.of_int n) 60_000L

let bar ~minute_num ~open_ticks ~high_ticks ~low_ticks ~close_ticks =
  {
    Market.minute_start_ms = minute minute_num;
    open_ticks;
    high_ticks;
    low_ticks;
    close_ticks;
    buy_volume = 10;
    sell_volume = 20;
  }

let flat m =
  bar ~minute_num:m ~open_ticks:100 ~high_ticks:105
    ~low_ticks:95 ~close_ticks:100

let first = minute 100

let label ?(direction = Risk.Long) ?(stop_ticks = 90)
    ?(target_ticks = 110) ?(horizon_bars = 3) bars =
  Labeling.label ~regime:Quant.Ranging ~direction
    ~detected_at_ms:first ~entry_ticks:100 ~stop_ticks
    ~target_ticks ~horizon_bars ~future_bars:bars

let is_error = function Error _ -> true | _ -> false

let test_first_touch () =
  let long_target =
    bar ~minute_num:100 ~open_ticks:100 ~high_ticks:110
      ~low_ticks:99 ~close_ticks:108
  in
  let long_stop =
    bar ~minute_num:100 ~open_ticks:100 ~high_ticks:101
      ~low_ticks:90 ~close_ticks:91
  in
  expect
    (match label [ long_target ] with
    | Ok (Some e) ->
        e.Quant.outcome = Quant.Target_first
        && e.horizon_bars = 3
        && e.resolved_at_ms = minute 101
    | _ -> false)
    "Long should label target-first";
  expect
    (match label [ long_stop ] with
    | Ok (Some e) -> e.Quant.outcome = Quant.Stop_first
    | _ -> false)
    "Long should label stop-first";
  expect
    (match
       label ~direction:Risk.Short ~target_ticks:90
         ~stop_ticks:110 [ long_stop ]
     with
    | Ok (Some e) -> e.Quant.outcome = Quant.Target_first
    | _ -> false)
    "Short target-first is a falling price";
  expect
    (match
       label ~direction:Risk.Short ~target_ticks:90
         ~stop_ticks:110 [ long_target ]
     with
    | Ok (Some e) -> e.Quant.outcome = Quant.Stop_first
    | _ -> false)
    "Short stop-first is a rising price";
  expect
    (match label [ flat 100; flat 101; flat 102 ] with
    | Ok (Some e) ->
        e.Quant.outcome = Quant.Time_limit
        && e.resolved_at_ms = minute 103
    | _ -> false)
    "Time barrier should classify a non-target";
  expect
    (match label [ flat 100; flat 101 ] with
    | Ok None -> true
    | _ -> false)
    "Insufficient observation horizon should not become a loss";
  expect
    (is_error
       (label
          [
            bar ~minute_num:100 ~open_ticks:100 ~high_ticks:111
              ~low_ticks:89 ~close_ticks:100;
          ]))
    "Both levels inside a single OHLC bar are ambiguous";
  expect
    (is_error (label [ flat 101 ]))
    "Missing first future bar should reject";
  expect
    (is_error (label [ flat 100; flat 102 ]))
    "Missing middle minute should reject";
  expect
    (is_error (label ~stop_ticks:105 [ flat 100 ]))
    "Invalid stop orientation should reject";
  expect
    (is_error (label ~horizon_bars:0 [ flat 100 ]))
    "Invalid horizon should reject"

let () =
  test_first_touch ();
  print_endline "All event labeling tests passed."
