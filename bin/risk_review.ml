open Mnq_core.Survival

(* Only the report schema is serialized. No private files or external services
   are consulted. Strings may contain operator-entered evidence references. *)
let string s =
  let b = Buffer.create (String.length s + 2) in
  Buffer.add_char b '"';
  String.iter (function
    | '"' -> Buffer.add_string b "\\\""
    | '\\' -> Buffer.add_string b "\\\\"
    | c when Char.code c < 32 || Char.code c > 126 ->
        Printf.bprintf b "\\u%04x" (Char.code c)
    | c -> Buffer.add_char b c) s;
  Buffer.add_char b '"';
  Buffer.contents b

let number = Int64.to_string
let nullable fn = function None -> "null" | Some value -> fn value
let obj fields =
  "{" ^ String.concat "," (List.map (fun (k, v) -> string k ^ ":" ^ v) fields) ^ "}"

let account_json (a : account) =
  obj [ "account_id", string a.account_id; "stage", string a.stage;
        "source", string a.source; "rule_source", string a.rule_source;
        "rule_model", string a.rule_model; "nominal_cents", number a.nominal;
        "cash_adjustments_cents", number a.cash_adjustments;
        "realized_since_inception_cents", number a.realized;
        "unrealized_cents", number a.unrealized; "marked_equity_cents", number a.marked_equity;
        "highest_eod_reference_cents", nullable number a.high_water;
        "floor_cents", number a.floor; "reserve_cents", number a.reserve;
        "incremental_open_pending_downside_cents", number a.open_downside;
        "daily_loss_limit_cents", number a.daily_limit;
        "session_start_equity_cents", number a.session_start_equity;
        "account_active", string_of_bool a.active; "day_trading_enabled", string_of_bool a.day_enabled;
        "gross_daily_headroom_cents", number a.daily_headroom;
        "gross_personal_daily_remaining_cents", number a.personal_remaining;
        "remaining_trades", number (Int64.max 0L (Int64.sub 2L a.trades_today));
        "firm_remaining_contracts", number a.firm_remaining;
        "personal_remaining_contracts", number a.personal_remaining_contracts;
        "buying_power_remaining_contracts", number a.margin_remaining ]

let proposal_json p =
  obj [ "instrument", string p.instrument; "contract_month", string p.contract_month;
        "direction", string (match p.direction with Mnq_core.Risk.Long -> "long" | Short -> "short");
        "entry_price_ticks", number p.entry_ticks; "stop_price_ticks", number p.stop_ticks;
        "requested_contracts", number p.requested; "tick_value_cents", number p.tick_cents;
        "observed_at_ms", number p.observed_at_ms; "execution_assumptions_source", string p.cost_source;
        "round_trip_fees_per_contract_cents", number p.variable_fees;
        "other_costs_per_contract_cents", number p.other_variable;
        "fixed_round_trip_cost_cents", number p.fixed_cost;
        "stress_slippage_ticks", number p.slippage; "failed_stop_extra_ticks", number p.failure_extra ]

(* Render exact quarter points without a floating-point conversion. *)
let points ticks = Printf.sprintf "%Ld.%02Ld" (Int64.div ticks 4L) (Int64.mul (Int64.rem ticks 4L) 25L)

let sizing_json s =
  obj [ "stop_distance_points", points s.stop_distance; "stop_distance_ticks", number s.stop_distance;
        "price_risk_per_contract_cents", number s.price_risk;
        "slippage_per_contract_cents", number s.slippage_cost;
        "planned_loss_per_contract_ex_fixed_cents", number s.planned_unit_loss;
        "stressed_loss_per_contract_ex_fixed_cents", number s.stressed_unit_loss;
        "gross_drawdown_headroom_cents", number s.gross_headroom;
        "account_budget_cents", number s.account_budget; "new_trade_budget_cents", number s.budget;
        "planned_max_by_risk", number s.planned_max;
        "mathematical_max_under_limits", number s.max_contracts;
        "requested_planned_loss_cents", number s.requested_planned;
        "requested_stress_loss_cents", number s.requested_stressed ]

let json (r : report) =
  obj [ "status", string (status_name r.status); "reason", string r.reason;
        "review_contracts", number r.review_contracts; "as_of_ms", number r.as_of_ms;
        "provenance", nullable (fun (a : account) -> string a.provenance) r.account;
        "account_observed_at_ms", nullable (fun (a : account) -> number a.observed_at_ms) r.account;
        "account", nullable account_json r.account; "proposal", nullable proposal_json r.proposal;
        "sizing", nullable sizing_json r.sizing ]

let read_lines channel =
  let rec loop acc =
    match input_line channel with
    | s -> loop (s :: acc)
    | exception End_of_file -> List.rev acc in
  loop []

let () =
  match Array.to_list Sys.argv with
  | [_; "--as-of-ms"; time; filename] ->
      (match Int64.of_string_opt time with
       | None -> prerr_endline "Invalid --as-of-ms"; exit 2
       | Some as_of_ms ->
           let result =
             try
               let ch = open_in filename in
               Fun.protect ~finally:(fun () -> close_in_noerr ch)
                 (fun () -> review ~as_of_ms (read_lines ch))
             with Sys_error _ -> unverified ~as_of_ms "Unable to read snapshot file" in
           print_endline (json result))
  | _ -> prerr_endline "Usage: risk_review --as-of-ms EPOCH_MILLISECONDS SNAPSHOT_FILE"; exit 2
