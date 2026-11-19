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

let () =
  if Array.length Sys.argv = 2 && Sys.argv.(1) = "--price-replay" then
    price_replay ()
  else (
    print_endline "MNQ Agent: offline historical research only.";
    print_endline
      "Run --price-replay with prepared historical OHLC price CSV. No live or delayed market-price feed is installed.")
