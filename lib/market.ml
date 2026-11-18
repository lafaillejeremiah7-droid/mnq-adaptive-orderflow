(** Deterministic, one-minute MNQ trade-print aggregation. Prices are integer
    0.25-point ticks; timestamps are Unix milliseconds. *)

type aggressor = Buyer | Seller

type trade = {
  timestamp_ms : int64;
  price_ticks : int;
  quantity : int;
  aggressor : aggressor;
}

type bar = {
  minute_start_ms : int64;
  open_ticks : int;
  high_ticks : int;
  low_ticks : int;
  close_ticks : int;
  buy_volume : int;
  sell_volume : int;
}

type state = {
  active : bar option;
  last_timestamp_ms : int64 option;
}

type error = Invalid_trade of string | Out_of_order | Missing_minute

let empty = { active = None; last_timestamp_ms = None }
let minute_start timestamp_ms =
  Int64.mul (Int64.div timestamp_ms 60_000L) 60_000L

let delta bar = bar.buy_volume - bar.sell_volume
let volume bar = bar.buy_volume + bar.sell_volume

let new_bar trade =
  let buy_volume, sell_volume =
    match trade.aggressor with
    | Buyer -> (trade.quantity, 0)
    | Seller -> (0, trade.quantity)
  in
  {
    minute_start_ms = minute_start trade.timestamp_ms;
    open_ticks = trade.price_ticks;
    high_ticks = trade.price_ticks;
    low_ticks = trade.price_ticks;
    close_ticks = trade.price_ticks;
    buy_volume;
    sell_volume;
  }

let update_bar bar trade =
  {
    bar with
    high_ticks = max bar.high_ticks trade.price_ticks;
    low_ticks = min bar.low_ticks trade.price_ticks;
    close_ticks = trade.price_ticks;
    buy_volume =
      bar.buy_volume
      + (if trade.aggressor = Buyer then trade.quantity else 0);
    sell_volume =
      bar.sell_volume
      + (if trade.aggressor = Seller then trade.quantity else 0);
  }

(** Returns a completed bar only after the first trade in the next minute.
    A missing minute fails closed; caller must reinitialize and backfill. *)
let on_trade state trade =
  if Int64.compare trade.timestamp_ms 0L < 0 then
    Error (Invalid_trade "Negative timestamp")
  else if trade.price_ticks <= 0 || trade.quantity <= 0 then
    Error (Invalid_trade "Price ticks and quantity must be positive")
  else
    match state.last_timestamp_ms with
    | Some previous when Int64.compare trade.timestamp_ms previous < 0 ->
        Error Out_of_order
    | _ ->
        let minute = minute_start trade.timestamp_ms in
        let next_state active =
          { active; last_timestamp_ms = Some trade.timestamp_ms }
        in
        match state.active with
        | None -> Ok (next_state (Some (new_bar trade)), None)
        | Some bar when Int64.equal minute bar.minute_start_ms ->
            Ok (next_state (Some (update_bar bar trade)), None)
        | Some bar
          when Int64.compare minute
                 (Int64.add bar.minute_start_ms 60_000L) > 0 ->
            Error Missing_minute
        | Some bar -> Ok (next_state (Some (new_bar trade)), Some bar)
