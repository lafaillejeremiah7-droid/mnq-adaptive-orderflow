open Mnq_core

let expect ok message = if not ok then failwith message

let test_prices () =
  let good = "6000000,80000,80004,79996,80002" in
  let candle =
    match Price_stream.parse good with
    | Ok bar -> bar
    | Error why -> failwith why
  in
  expect (candle.Market.minute_start_ms = 6_000_000L)
    "Timestamp should stay in Unix ms";
  expect (candle.Market.close_ticks = 80002) "Wrong close tick";
  expect (candle.Market.buy_volume = 0 && candle.Market.sell_volume = 0)
    "Price-only feed must not invent aggressive trade quantities";
  expect
    (match Quant.on_closed_bar Quant.empty candle with
    | Ok (_, None) -> true
    | _ -> false)
    "Quant engine must accept price-only bars";
  List.iter
    (fun row ->
      expect
        (match Price_stream.parse row with
        | Error _ -> true
        | _ -> false)
        ("Bad price-only input accepted: " ^ row))
    [
      "6000001,80000,80004,79996,80002";
      "6000000,80000,79996,80004,80002";
      "6000000,80000,80004,79996,80005";
      "6000000,80000,80004,79996";
      "a,80000,80004,79996,80002";
      "-60000,80000,80004,79996,80002";
    ]

let () =
  test_prices ();
  print_endline "Price-only adapter tests passed."
