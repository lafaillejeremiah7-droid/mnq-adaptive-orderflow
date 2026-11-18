(** Pure stream feature accumulator. Snapshot excludes the first print of the
    next minute, which is what confirms that the previous bar has closed. *)

type snapshot = {
  closed_bar : Market.bar;
  cumulative_delta_since_start : int;
  profile_since_start : Profile.value_area option;
  completed_minute_profile : Profile.value_area option;
}

type state = {
  market : Market.state;
  stream_profile : Profile.t;
  minute_profile : Profile.t;
  cumulative_delta : int;
}

let empty =
  {
    market = Market.empty;
    stream_profile = Profile.empty;
    minute_profile = Profile.empty;
    cumulative_delta = 0;
  }

let on_trade state trade =
  match Market.on_trade state.market trade with
  | Error error -> Error error
  | Ok (market, completed) ->
      let snapshot =
        match completed with
        | None -> None
        | Some closed_bar ->
            Some
              {
                closed_bar;
                cumulative_delta_since_start = state.cumulative_delta;
                profile_since_start = Profile.value_area state.stream_profile;
                completed_minute_profile = Profile.value_area state.minute_profile;
              }
      in
      let minute_profile =
        if Option.is_some completed then Profile.empty else state.minute_profile
      in
      let change =
        match trade.Market.aggressor with
        | Market.Buyer -> trade.quantity
        | Market.Seller -> -trade.quantity
      in
      Ok
        ( {
            market;
            stream_profile = Profile.add_trade state.stream_profile trade;
            minute_profile = Profile.add_trade minute_profile trade;
            cumulative_delta = state.cumulative_delta + change;
          },
          snapshot )
