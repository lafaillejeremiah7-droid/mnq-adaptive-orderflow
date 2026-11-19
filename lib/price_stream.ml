(** Price-only minute bar adapter.
    Input: timestamp_ms,open_ticks,high_ticks,low_ticks,close_ticks
    Prices are 0.25-point tick units. No order-flow measurements are read,
    estimated or synthesized by this adapter. *)

let parse line =
  let values = String.split_on_char ',' (String.trim line) in
  match values with
  | [ timestamp; o; h; l; c ] -> (
      match
        ( Int64.of_string_opt (String.trim timestamp),
          int_of_string_opt (String.trim o),
          int_of_string_opt (String.trim h),
          int_of_string_opt (String.trim l),
          int_of_string_opt (String.trim c) )
      with
      | Some minute_start_ms, Some open_ticks, Some high_ticks,
        Some low_ticks, Some close_ticks ->
          if Int64.compare minute_start_ms 0L < 0
             || not (Int64.equal (Int64.rem minute_start_ms 60_000L) 0L)
             || low_ticks <= 0 || high_ticks < low_ticks
             || open_ticks < low_ticks || open_ticks > high_ticks
             || close_ticks < low_ticks || close_ticks > high_ticks then
            Error "Invalid OHLC, tick values, or minute timestamp"
          else
            Ok
              {
                Market.minute_start_ms;
                open_ticks;
                high_ticks;
                low_ticks;
                close_ticks;
                (* Price-only inputs have no signed aggressor data.
                   These fields are unused by Quant.on_closed_bar. *)
                buy_volume = 0;
                sell_volume = 0;
              }
      | _ -> Error "CSV contains invalid numeric fields")
  | _ -> Error "Expected timestamp_ms,open_ticks,high_ticks,low_ticks,close_ticks"
