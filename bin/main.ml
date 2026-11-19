let regime_name = function
  | Mnq_core.Quant.Trending_up -> "TREND_UP"
  | Mnq_core.Quant.Trending_down -> "TREND_DOWN"
  | Mnq_core.Quant.Ranging -> "RANGE"
  | Mnq_core.Quant.Volatility_spike -> "VOLATILITY_SPIKE"

(** Advisory-only, price-only stream. Does not receive or calculate
    volume profiles, delta, book activity, or absorption. *)
let price_stream () =
  let state = ref Mnq_core.Quant.empty in
  let rec consume () =
    match input_line stdin with
    | line ->
        let bar =
          match Mnq_core.Price_stream.parse line with
          | Ok bar -> bar
          | Error reason ->
              Printf.eprintf "STOP invalid price feed: %s\n%!" reason;
              exit 2
        in
        (match Mnq_core.Quant.on_closed_bar !state bar with
        | Error reason ->
            Printf.eprintf "STOP nonconsecutive/invalid price feed: %s\n%!"
              reason;
            exit 2
        | Ok (next, measurement) ->
            state := next;
            (match measurement with
            | None -> Printf.printf "WAIT insufficient completed price bars\n%!"
            | Some (m : Mnq_core.Quant.measurement) ->
                Printf.printf
                  "REGIME %s close_minute_ms=%Ld efficiency=%.4f fast_tr_ticks=%.2f slow_tr_ticks=%.2f (RESEARCH_ONLY)\n%!"
                  (regime_name m.regime)
                  m.closed_minute_start_ms
                  m.efficiency_ratio
                  m.fast_true_range_ticks
                  m.slow_true_range_ticks));
        consume ()
    | exception End_of_file -> ()
  in
  consume ()

(** Offline historical replay: never reads orders, volume or order flow. *)
let price_replay () =
  let state = ref Mnq_core.Replay.empty in
  let rec consume () =
    match input_line stdin with
    | line ->
        if String.trim line <> "" then (
          let bar =
            match Mnq_core.Price_stream.parse line with
            | Ok value -> value
            | Error reason ->
                Printf.eprintf "ERROR invalid historical price row: %s\n%!" reason;
                exit 2
          in
          match Mnq_core.Replay.append !state bar with
          | Ok next -> state := next
          | Error reason ->
              Printf.eprintf "ERROR invalid historical sequence: %s\n%!" reason;
              exit 2);
        consume ()
    | exception End_of_file ->
        let s = !state in
        Printf.printf
          "HISTORICAL_PRICE_ONLY bars=%d segments=%d classified=%d longest_consecutive_bars=%d trend_up=%d trend_down=%d range=%d volatility_spike=%d (DESCRIPTIVE_ONLY; NOT A BACKTEST OF TRADE PROFITS)\n%!"
          s.bars s.segments s.classified s.longest_segment
          s.counts.up s.counts.down s.counts.range s.counts.spike
  in
  consume ()

(** Live NQ futures price-only reader. No order-flow data or trades. *)
let live_nq_price () =
  let latest = ref None in
  let rec consume () =
    match input_line stdin with
    | line ->
        let quote =
          match Mnq_core.Latest_quote.parse line with
          | Ok quote -> quote
          | Error reason ->
              Printf.eprintf "STOP invalid NQ quote: %s\n%!" reason;
              exit 2
        in
        (match Mnq_core.Latest_quote.accept !latest quote with
        | Error reason ->
            Printf.eprintf "STOP NQ quote stream: %s\n%!" reason;
            exit 2
        | Ok next ->
            latest := next;
            Printf.printf
              "NQ_FUTURES LAST_PRICE=%.2f USD_INDEX_POINTS as_of_utc_ms=%Ld (PRICE_ONLY)\n%!"
              (Mnq_core.Latest_quote.points quote) quote.as_of_ms);
        consume ()
    | exception End_of_file ->
        Printf.eprintf
          "NQ price feed ended; prices are no longer updating.\n%!"
  in
  consume ()

(** No-key Yahoo NQ=F stream: DELAYED market prices, not live CME quotes. *)
let delayed_nq_price () =
  let latest = ref None in
  let rec consume () =
    match input_line stdin with
    | line ->
        let quote =
          match Mnq_core.Latest_quote.parse line with
          | Ok quote -> quote
          | Error reason ->
              Printf.eprintf "STOP invalid delayed NQ price: %s\n%!" reason;
              exit 2
        in
        (match Mnq_core.Latest_quote.accept !latest quote with
        | Error reason ->
            Printf.eprintf "STOP delayed NQ source: %s\n%!" reason;
            exit 2
        | Ok next ->
            latest := next;
            Printf.printf
              "NQ_FUTURES DELAYED_PRICE=%.2f INDEX_POINTS as_of_utc_ms=%Ld SOURCE=YAHOO_NQ=F (NOT_LIVE)\n%!"
              (Mnq_core.Latest_quote.points quote) quote.as_of_ms);
        consume ()
    | exception End_of_file ->
        Printf.eprintf "Delayed NQ source ended; no new price.\n%!"
  in
  consume ()

let () =
  if Array.length Sys.argv = 2 && Sys.argv.(1) = "--price-stream" then
    price_stream ()
  else if Array.length Sys.argv = 2 && Sys.argv.(1) = "--delayed-nq-price" then
    delayed_nq_price ()
  else if Array.length Sys.argv = 2 && Sys.argv.(1) = "--live-nq-price" then
    live_nq_price ()
  else if Array.length Sys.argv = 2 && Sys.argv.(1) = "--price-replay" then
    price_replay ()
  else (
    print_endline "MNQ Agent: OCaml core initialized.";
    print_endline
      "Use --price-stream with validated CME price-only OHLC input. No live feed or order execution is configured by default.")
