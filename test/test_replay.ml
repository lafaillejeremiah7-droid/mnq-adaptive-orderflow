open Mnq_core

let expect condition message = if not condition then failwith message

let make_bar minute close =
  {
    Market.minute_start_ms = Int64.mul (Int64.of_int minute) 60_000L;
    open_ticks = close;
    high_ticks = close + 2;
    low_ticks = close - 2;
    close_ticks = close;
    buy_volume = 0;
    sell_volume = 0;
  }

let append s bar =
  match Replay.append s bar with
  | Ok next -> next
  | Error message -> failwith message

let run () =
  let state =
    List.fold_left
      (fun state i -> append state (make_bar (100 + i) (80000 + i)))
      Replay.empty (List.init 25 Fun.id)
  in
  expect (state.bars = 25) "Expected 25 bars";
  expect (state.segments = 1) "Expected one contiguous segment";
  expect (state.classified = 5) "Must only classify after 21 bars";
  expect (state.counts.up = 5) "Expected trending-up regime on monotone bars";
  expect (state.longest_segment = 25) "Longest segment incorrect";
  let reset = append state (make_bar 200 81000) in
  expect (reset.segments = 2) "Gap should reset warmup";
  expect (reset.classified = 5) "Gap must not classify across missing bars";
  let after =
    List.fold_left
      (fun state i -> append state (make_bar (201 + i) (81000 + i)))
      reset (List.init 20 Fun.id)
  in
  expect (after.classified = 6) "Classify only after second warmup";
  expect
    (match Replay.append after (make_bar 220 81020) with
    | Error _ -> true
    | Ok _ -> false)
    "Duplicate historical minute must be rejected";
  expect
    (match Replay.append after (make_bar 199 80999) with
    | Error _ -> true
    | Ok _ -> false)
    "Backwards historical minute must be rejected";
  expect
    (match Replay.append Replay.empty (make_bar 10 (-10)) with
    | Error _ -> true
    | Ok _ -> false)
    "Invalid price bars must be rejected"

let () =
  run ();
  print_endline "Historical price replay tests passed."
