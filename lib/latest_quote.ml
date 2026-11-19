(** Single-instrument, price-only NQ futures quotes from completed
    1-second CME price bars. No volume, order-flow or trading state. *)

type quote = {
  as_of_ms : int64;
  price_ticks : int;
}

let parse line =
  match String.split_on_char ',' (String.trim line) with
  | [ time; price ] -> (
      match
        ( Int64.of_string_opt (String.trim time),
          int_of_string_opt (String.trim price) )
      with
      | Some as_of_ms, Some price_ticks
        when Int64.compare as_of_ms 0L >= 0
             && Int64.rem as_of_ms 1_000L = 0L
             && price_ticks > 0
             && price_ticks <= 1_000_000 ->
          Ok { as_of_ms; price_ticks }
      | _ -> Error "Invalid price tick or event timestamp")
  | _ -> Error "Expected as_of_utc_ms,price_ticks"

let accept previous quote =
  match previous with
  | Some old when Int64.compare quote.as_of_ms old.as_of_ms <= 0 ->
      Error "Duplicate or out-of-order NQ quote"
  | _ -> Ok (Some quote)

let points quote = float_of_int quote.price_ticks /. 4.0
