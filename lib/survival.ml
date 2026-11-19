(** Offline, as-of account review for outright MNQ/NQ. Sources are human
    attestations or illustrative fixtures. The return type has no order action. *)

module Fields = Map.Make (String)
module Money = Checked_int64

type status =
  | Data_unverified | Account_at_risk | Risk_blocked | No_safe_contract_size
  | No_validated_edge | No_trade | Research_review_only

let status_name = function
  | Data_unverified -> "DATA_UNVERIFIED" | Account_at_risk -> "ACCOUNT_AT_RISK"
  | Risk_blocked -> "RISK_BLOCKED" | No_safe_contract_size -> "NO_SAFE_CONTRACT_SIZE"
  | No_validated_edge -> "NO_VALIDATED_EDGE" | No_trade -> "NO_TRADE"
  | Research_review_only -> "RESEARCH_REVIEW_ONLY"

type account = {
  provenance : string; account_id : string; stage : string; source : string;
  rule_source : string; rule_model : string; observed_at_ms : int64;
  nominal : int64; cash_adjustments : int64; realized : int64; unrealized : int64;
  marked_equity : int64; high_water : int64 option; floor : int64;
  active : bool; day_enabled : bool; session_start_equity : int64; daily_limit : int64;
  reserve : int64; open_downside : int64; daily_headroom : int64;
  personal_remaining : int64; trades_today : int64; consecutive_losses : int64;
  risk_ceiling : int64; firm_remaining : int64; personal_remaining_contracts : int64;
  margin_remaining : int64; simultaneous_allowed : bool; occupied : bool;
}

type proposal = {
  instrument : string; contract_month : string; direction : Risk.direction;
  entry_ticks : int64; stop_ticks : int64; requested : int64; tick_cents : int64;
  observed_at_ms : int64; last_trade_ms : int64; setup_eligible : bool;
  edge_review : string; market_eligible : bool; cost_source : string;
  variable_fees : int64; other_variable : int64; fixed_cost : int64;
  slippage : int64; calibration_worst : int64; failure_extra : int64;
}

type sizing = {
  stop_distance : int64; price_risk : int64; slippage_cost : int64;
  planned_unit_loss : int64; stressed_unit_loss : int64;
  gross_headroom : int64; account_budget : int64; budget : int64;
  planned_max : int64; max_contracts : int64; requested_planned : int64;
  requested_stressed : int64;
}

type report = {
  status : status; reason : string; as_of_ms : int64; review_contracts : int64;
  account : account option; proposal : proposal option; sizing : sizing option;
}

let unverified ~as_of_ms reason =
  { status = Data_unverified; reason; as_of_ms; review_contracts = 0L;
    account = None; proposal = None; sizing = None }

exception Invalid of string
let invalid message = raise (Invalid message)
let require condition message = if not condition then invalid message

let read_fields lines =
  List.fold_left (fun fields raw ->
      let line = String.trim raw in
      if line = "" || line.[0] = '#' then fields
      else match String.index_opt line '=' with
        | None -> invalid "Expected one key=value per line"
        | Some index ->
            let k = String.sub line 0 index |> String.trim in
            let v = String.sub line (index+1) (String.length line-index-1) |> String.trim in
            require (k <> "" && v <> "") ("Empty key or value: " ^ k);
            require (not (Fields.mem k fields)) ("Duplicate field: " ^ k);
            Fields.add k v fields)
    Fields.empty lines

type reader = { mutable remaining : string Fields.t }
let field r name =
  match Fields.find_opt name r.remaining with
  | None -> invalid ("Missing field: " ^ name)
  | Some s -> r.remaining <- Fields.remove name r.remaining; s

let identifier r name =
  let s = field r name in
  require (String.length s <= 256 && String.for_all (fun c -> c >= ' ' && c <= '~') s
           && not (List.mem (String.lowercase_ascii s) ["unknown"; "none"; "unverified"]))
    ("Missing or invalid reference: " ^ name);
  s

let digits c = c >= '0' && c <= '9'
let integer r name =
  let s = field r name in
  let start = if s.[0] = '-' then 1 else 0 in
  let n = String.length s - start in
  require (n > 0 && String.for_all digits (String.sub s start n))
    ("Expected a decimal integer: " ^ name);
  match Int64.of_string_opt s with
  | Some v -> v | None -> invalid ("Integer out of range: " ^ name)

let nonnegative r name =
  let v = integer r name in require (v >= 0L) ("Negative field: " ^ name); v

let positive r name =
  let v = integer r name in require (v > 0L) ("Expected positive field: " ^ name); v

let choice r name allowed =
  let v = field r name in require (List.mem v allowed) ("Unsupported value: " ^ name); v
let boolean r name = choice r name ["true"; "false"] = "true"

let account r =
  let provenance = choice r "provenance" ["human_attested"; "illustrative"] in
  let account_id = identifier r "account_id" in
  let rule_id = identifier r "rule_account_id" in
  require (account_id = rule_id) "Account and rule evidence refer to different accounts";
  let stage = choice r "stage" ["evaluation"; "funded"; "payout_eligible"] in
  let source = identifier r "account_source" in
  let rule_source = identifier r "rule_source" in
  let rule_model = choice r "rule_model" ["fixed_marked_floor"; "eod_trailing_marked_floor"] in
  let observed_at_ms = nonnegative r "account_observed_at_ms" in
  let nominal = positive r "nominal_cents" in
  let cash_adjustments = integer r "cash_adjustments_cents" in
  let realized = integer r "realized_since_inception_cents" in
  let unrealized = integer r "unrealized_cents" in
  let marked_equity = integer r "marked_equity_cents" in
  require (Money.(add (add (add nominal cash_adjustments) realized) unrealized) = marked_equity)
    "Marked equity conflicts with nominal capital, ledger adjustments and P&L";
  let floor = nonnegative r "official_floor_cents" in
  let high_water, rule_floor = match rule_model with
    | "fixed_marked_floor" -> None, nonnegative r "fixed_floor_cents"
    | _ ->
        let peak = nonnegative r "highest_eod_reference_cents" in
        require (peak >= nominal) "Highest EOD reference is below the initial reference capital";
        let trail = positive r "trailing_distance_cents" in
        let raw = Money.sub peak trail in
        let cap = match Fields.find_opt "floor_cap_cents" r.remaining with
          | Some "none" -> ignore (field r "floor_cap_cents"); raw
          | _ -> Int64.min raw (nonnegative r "floor_cap_cents") in
        Some peak, cap in
  require (floor = rule_floor) "Official floor conflicts with the verified rule parameters";
  let reserve = nonnegative r "preservation_reserve_cents" in
  let occupied = boolean r "has_open_position_or_pending_order" in
  let open_downside = nonnegative r "incremental_open_pending_downside_cents" in
  require (occupied = (open_downside > 0L))
    "Open/pending position state conflicts with incremental downside";
  require (occupied || unrealized = 0L) "Flat account has nonzero unrealized P&L";
  let active = boolean r "account_active" in
  let day_enabled = boolean r "day_trading_enabled" in
  let session_start_equity = positive r "session_start_equity_cents" in
  let daily_limit = positive r "daily_loss_limit_cents" in
  let daily_headroom = nonnegative r "gross_daily_headroom_cents" in
  require (Int64.max 0L Money.(sub marked_equity (sub session_start_equity daily_limit)) = daily_headroom)
    "Daily headroom conflicts with the session-start marked equity rule";
  let personal_remaining = nonnegative r "gross_personal_daily_remaining_cents" in
  let trades_today = nonnegative r "trades_today" in
  let consecutive_losses = nonnegative r "consecutive_losses" in
  let risk_ceiling = nonnegative r "new_trade_ceiling_cents" in
  require (risk_ceiling <= 10_000L) "New-trade ceiling exceeds the personal $100 cap";
  let firm_remaining = nonnegative r "firm_remaining_contracts" in
  let personal_remaining_contracts = nonnegative r "personal_remaining_contracts" in
  let margin_remaining = nonnegative r "buying_power_remaining_contracts" in
  let simultaneous_allowed = boolean r "simultaneous_exposure_permitted" in
  { provenance; account_id; stage; source; rule_source; rule_model; observed_at_ms;
    nominal; cash_adjustments; realized; unrealized; marked_equity; high_water; floor;
    active; day_enabled; session_start_equity; daily_limit;
    reserve; open_downside; daily_headroom; personal_remaining; trades_today;
    consecutive_losses; risk_ceiling; firm_remaining; personal_remaining_contracts;
    margin_remaining; simultaneous_allowed; occupied }

let proposal r =
  let instrument = choice r "instrument" ["MNQ"; "NQ"] in
  require (field r "limits_for_instrument" = instrument)
    "Position and margin limits apply to a different contract product";
  let tick_cents = if instrument = "MNQ" then 50L else 500L in
  require (positive r "reported_tick_value_cents" = tick_cents)
    "Reported tick value conflicts with CME outright specifications";
  let contract_month = field r "contract_month" in
  require (String.length contract_month = 7 && contract_month.[4] = '-'
           && String.for_all digits (String.sub contract_month 0 4)
           && List.mem (String.sub contract_month 5 2) ["03"; "06"; "09"; "12"])
    "Expected an outright quarterly contract month YYYY-MM";
  let last_trade_ms = positive r "contract_last_trade_ms" in
  let expiry = Unix.gmtime (Int64.to_float last_trade_ms /. 1_000.) in
  require (Printf.sprintf "%04d-%02d" (expiry.tm_year + 1900) (expiry.tm_mon + 1) = contract_month)
    "Last-trade timestamp conflicts with the contract month";
  let direction = if choice r "direction" ["long"; "short"] = "long" then Risk.Long else Risk.Short in
  let entry_ticks = positive r "entry_price_ticks" in
  let stop_ticks = positive r "stop_price_ticks" in
  require ((direction = Risk.Long && stop_ticks < entry_ticks)
           || (direction = Risk.Short && stop_ticks > entry_ticks))
    "Stop must lie on the loss side of the proposed entry";
  let requested = positive r "requested_contracts" in
  let observed_at_ms = nonnegative r "proposal_observed_at_ms" in
  let setup_eligible = boolean r "predefined_setup_eligible" in
  let edge_review = choice r "edge_review" ["insufficient"; "independently_reviewed"] in
  if edge_review = "independently_reviewed" then ignore (identifier r "edge_review_source");
  let market_eligible = boolean r "session_and_market_data_verified" in
  let cost_source = identifier r "execution_assumptions_source" in
  let variable_fees = nonnegative r "round_trip_fees_per_contract_cents" in
  let other_variable = nonnegative r "other_costs_per_contract_cents" in
  let fixed_cost = nonnegative r "fixed_round_trip_cost_cents" in
  let slippage = nonnegative r "stress_slippage_ticks" in
  let calibration_worst = nonnegative r "observed_adverse_slippage_ticks" in
  let failure_extra = positive r "failed_stop_extra_ticks" in
  { instrument; contract_month; direction; entry_ticks; stop_ticks; requested; tick_cents;
    observed_at_ms; last_trade_ms; setup_eligible; edge_review; market_eligible;
    cost_source; variable_fees; other_variable; fixed_cost; slippage; calibration_worst; failure_extra }

let floor_zero = Int64.max 0L

let sizing a p =
  let open Money in
  let stop_distance = Int64.abs (sub p.entry_ticks p.stop_ticks) in
  let price_risk = mul_nonnegative stop_distance p.tick_cents in
  let slippage_cost = mul_nonnegative p.slippage p.tick_cents in
  let planned_unit_loss = add (add price_risk slippage_cost) (add p.variable_fees p.other_variable) in
  let stressed_unit_loss = add planned_unit_loss (mul_nonnegative p.failure_extra p.tick_cents) in
  let gross_headroom = sub a.marked_equity a.floor in
  (* Touching an inclusive failure threshold is a breach, even with a zero reserve.
     Subtract each exposure from nonnegative capacity before taking the minimum. *)
  let after capacity deduction = floor_zero (sub (floor_zero capacity) deduction) in
  let account_budget = after (after gross_headroom (Int64.max 1L a.reserve)) a.open_downside in
  let daily = after (after a.daily_headroom 1L) a.open_downside in
  let personal = after a.personal_remaining a.open_downside in
  let budget = List.fold_left Int64.min a.risk_ceiling [account_budget; daily; personal] in
  let variable_budget = after budget p.fixed_cost in
  let planned_max = Int64.div variable_budget planned_unit_loss in
  let trading_blocked = not a.active || not a.day_enabled || a.trades_today >= 2L
    || a.consecutive_losses >= 2L || (a.occupied && not a.simultaneous_allowed) in
  let max_contracts = if trading_blocked then 0L else
      List.fold_left Int64.min (Int64.div variable_budget stressed_unit_loss)
        [a.firm_remaining; a.personal_remaining_contracts; a.margin_remaining] in
  let requested_planned = add p.fixed_cost (mul_nonnegative p.requested planned_unit_loss) in
  let requested_stressed = add p.fixed_cost (mul_nonnegative p.requested stressed_unit_loss) in
  { stop_distance; price_risk; slippage_cost; planned_unit_loss; stressed_unit_loss;
    gross_headroom; account_budget; budget; planned_max; max_contracts;
    requested_planned; requested_stressed }

let review ~as_of_ms lines =
  let empty = unverified ~as_of_ms "Unverified input" in
  let context = ref empty in
  let stale observed max_age =
    observed > as_of_ms || Int64.sub as_of_ms observed > max_age in
  try
    require (as_of_ms >= 0L) "Invalid as-of timestamp";
    let r = { remaining = read_fields lines } in
    let a = account r in
    context := { !context with account = Some a };
    let p = proposal r in
    context := { !context with proposal = Some p };
    require (Fields.is_empty r.remaining)
      ("Unknown or inapplicable fields: " ^ String.concat ", " (List.map fst (Fields.bindings r.remaining)));
    require (not (stale a.observed_at_ms 30_000L)) "Account snapshot is future-dated or older than 30 seconds";
    require (not (stale p.observed_at_ms 120_000L)) "Market proposal is future-dated or older than 120 seconds";
    require (as_of_ms < p.last_trade_ms) "Contract last-trade time has passed";
    require p.market_eligible "Session or market observations unverified";
    require (p.calibration_worst <= p.slippage) "Observed adverse slippage exceeds the stress assumption";
    let s = sizing a p in
    context := { !context with sizing = Some s };
    let finish status reason = { !context with status; reason } in
    if not a.active then finish Account_at_risk "Account is inactive or a terminal breach was reported"
    else if s.gross_headroom <= 0L then finish Account_at_risk "Marked equity touched or breached the official floor"
    else if s.account_budget = 0L then finish Account_at_risk "Reserve and additional open exposure consume drawdown capacity"
    else if not a.day_enabled then finish Risk_blocked "Account has a daily trading lockout"
    else if a.trades_today >= 2L || a.consecutive_losses >= 2L then finish Risk_blocked "Daily trade count or consecutive-loss stop reached"
    else if a.occupied && not a.simultaneous_allowed then finish Risk_blocked "Simultaneous exposure is prohibited"
    else if s.budget = 0L then finish Risk_blocked "Daily, personal or per-trade risk budget exhausted"
    else if s.max_contracts = 0L then finish No_safe_contract_size "Even one contract exceeds a verified capacity or stress limit"
    else if p.requested > s.max_contracts then finish Risk_blocked "Requested contracts exceed the calculated maximum"
    else if not p.setup_eligible then finish No_trade "No eligible predefined setup"
    else if p.edge_review = "insufficient" then finish No_validated_edge "Independent evidence was not supplied"
    else { !context with status = Research_review_only; reason = "Within supplied assumptions for offline review";
                         review_contracts = p.requested }
  with
  | Invalid reason -> { !context with reason }
  | Checked_int64.Overflow -> { !context with reason = "Arithmetic outside exact int64 range" }
  | Unix.Unix_error _ -> { !context with reason = "Timestamp outside supported calendar range" }
