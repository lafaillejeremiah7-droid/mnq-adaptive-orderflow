(** Fail-closed advisory gate. Monetary amounts are int64 cents; price ticks
    are 0.25 index points ($0.50 per MNQ tick per contract). No order execution. *)

type direction = Long | Short

type signal = {
  direction : direction;
  observed_at_ms : int64;
}

type account = {
  observed_at_ms : int64;
  equity_cents : int64;
  drawdown_floor_cents : int64;
  day_net_cents : int64;
  trades_today : int;
  consecutive_losses : int;
  open_contracts : int;
}

type proposal = {
  direction : direction;
  entry_ticks : int;
  stop_ticks : int;
  contracts : int;
}

type limits = {
  risk_per_trade_cents : int64;
  daily_stop_cents : int64;
  max_trades_per_day : int;
  max_consecutive_losses : int;
  max_contracts : int;
  drawdown_reserve_cents : int64;
  round_trip_cost_cents_per_contract : int64;
  slippage_ticks : int;
}

type verdict =
  | Blocked of string list
  | Review_only of {
      estimated_loss_cents : int64;
      available_risk_cents : int64;
    }

let default_limits =
  {
    risk_per_trade_cents = 10_000L;
    daily_stop_cents = 20_000L;
    max_trades_per_day = 2;
    max_consecutive_losses = 2;
    max_contracts = 2;
    drawdown_reserve_cents = 15_000L;
    round_trip_cost_cents_per_contract = 250L;
    slippage_ticks = 2;
  }

let min3 a b c = Int64.min a (Int64.min b c)

let check ~now_ms ~session_open ~feed_healthy ~(signal : signal option)
    ~(account : account) ~(proposal : proposal) ~(limits : limits) =
  let failures = ref [] in
  let reject reason = failures := reason :: !failures in
  if not session_open then reject "Outside approved trading session";
  if not feed_healthy then reject "Market feed not verified healthy";
  if Int64.compare now_ms 0L < 0 then reject "Invalid current timestamp";
  let stale timestamp limit =
    timestamp < 0L || timestamp > now_ms || Int64.sub now_ms timestamp > limit
  in
  if stale account.observed_at_ms 30_000L then
    reject "Broker account snapshot missing, future-dated, or older than 30s";
  (match signal with
  | None -> reject "No validated matching setup candidate"
  | Some candidate ->
      if candidate.direction <> proposal.direction
         || stale candidate.observed_at_ms 120_000L then
        reject "Signal direction mismatch or candidate is stale");
  if account.trades_today < 0 || account.consecutive_losses < 0
     || account.open_contracts < 0 then
    reject "Invalid broker trade counts";
  if account.trades_today >= min 2 limits.max_trades_per_day then
    reject "Maximum daily trade count reached";
  if account.consecutive_losses >= limits.max_consecutive_losses then
    reject "Consecutive-loss stop reached";
  if account.open_contracts <> 0 then reject "An open position already exists";
  if proposal.contracts < 1 || proposal.contracts > limits.max_contracts then
    reject "Contract count outside personal limit";
  if proposal.entry_ticks <= 0 || proposal.stop_ticks <= 0
     || proposal.entry_ticks > 1_000_000
     || proposal.stop_ticks > 1_000_000 then
    reject "Invalid MNQ tick prices";
  (match proposal.direction with
  | Long when proposal.stop_ticks >= proposal.entry_ticks ->
      reject "Long stop must be below entry"
  | Short when proposal.stop_ticks <= proposal.entry_ticks ->
      reject "Short stop must be above entry"
  | _ -> ());
  if Int64.compare limits.risk_per_trade_cents 0L <= 0
     || Int64.compare limits.daily_stop_cents 0L <= 0
     || limits.max_trades_per_day < 1 || limits.max_contracts < 1
     || limits.max_consecutive_losses < 1
     || limits.slippage_ticks < 0
     || Int64.compare limits.round_trip_cost_cents_per_contract 0L < 0
     || Int64.compare limits.drawdown_reserve_cents 0L < 0 then
    reject "Invalid risk limits";
  if account.drawdown_floor_cents < 0L then reject "Invalid broker drawdown floor";
  if Int64.compare account.equity_cents account.drawdown_floor_cents <= 0 then
    reject "Account at or below official drawdown floor";
  if !failures <> [] then Blocked (List.rev !failures)
  else
    try
      let open Checked_int64 in
      let contracts = Int64.of_int proposal.contracts in
      let distance = Int64.of_int (abs (proposal.entry_ticks - proposal.stop_ticks)) in
      let estimated_loss_cents =
        mul_nonnegative contracts
          (add (mul_nonnegative distance 50L)
             (add limits.round_trip_cost_cents_per_contract
                (mul_nonnegative (Int64.of_int limits.slippage_ticks) 50L)))
      in
      let available_risk_cents =
        min3 (Int64.min 10_000L limits.risk_per_trade_cents)
          (sub (add limits.daily_stop_cents account.day_net_cents) 1L)
          (sub (sub account.equity_cents account.drawdown_floor_cents)
             (Int64.max 1L limits.drawdown_reserve_cents))
      in
      if available_risk_cents <= 0L then
        Blocked [ "No remaining daily/drawdown risk budget" ]
      else if estimated_loss_cents > available_risk_cents then
        Blocked [ "Estimated stop loss including costs exceeds risk budget" ]
      else Review_only { estimated_loss_cents; available_risk_cents }
    with Checked_int64.Overflow -> Blocked [ "Risk arithmetic out of range" ]
