open Mnq_core
open Survival

let now = 1_760_000_000_000L

(* Strict parsing and the CLI share the same checked evaluator. Exercise it with
   the tracked fixture so a change to its schema must also pass this suite. *)
let fixture =
  let ch = open_in "../examples/ILLUSTRATIVE_risk_snapshot.txt" in
  Fun.protect ~finally:(fun () -> close_in ch) (fun () ->
      let rec loop acc =
        match input_line ch with line -> loop (line :: acc)
        | exception End_of_file -> read_fields acc in
      loop [])

let modify fields changes =
  List.fold_left (fun f (k, v) -> if v = "" then Fields.remove k f else Fields.add k v f) fields changes
let lines fields = Fields.bindings fields |> List.map (fun (k,v) -> k ^ "=" ^ v)
let roomy = modify fixture ["official_floor_cents","2900000"; "fixed_floor_cents","2900000";
                            "edge_review","independently_reviewed"; "edge_review_source","fixture outcome review"]
let run ?(base=roomy) changes = review ~as_of_ms:now (lines (modify base changes))
let expect msg x = if not x then failwith msg
let verdict name status report =
  expect (name ^ ": " ^ status_name report.status ^ " (" ^ report.reason ^ ")") (report.status = status);
  if status <> Research_review_only then expect (name ^ " nonzero rejection") (report.review_contracts = 0L)
let details report = Option.get report.sizing

let test_values () =
  let r = run ~base:fixture [] in
  verdict "illustrative D" No_safe_contract_size r;
  expect "$37 capacity" ((details r).budget = 3700L);
  let a = run [] in
  verdict "A" Research_review_only a;
  expect "$40 stop and included costs" ((details a).price_risk = 4000L
    && (details a).planned_unit_loss = 4350L && (details a).stressed_unit_loss = 4500L);
  let b = run ["requested_contracts","2"; "new_trade_ceiling_cents","8500"] in
  verdict "B" Risk_blocked b;
  expect "B rejects second contract" ((details b).requested_planned = 8700L && (details b).max_contracts = 1L);
  let c = run ["instrument","NQ"; "limits_for_instrument","NQ"; "reported_tick_value_cents","500"] in
  verdict "C" No_safe_contract_size c;
  expect "$400 NQ" ((details c).price_risk = 40000L);
  let fixed = run ["fixed_round_trip_cost_cents","300"; "requested_contracts","2"] in
  expect "fixed cost applied once" ((details fixed).requested_stressed = 9300L);
  let gap = run ["failed_stop_extra_ticks","150"] in
  verdict "failed stop" No_safe_contract_size gap;
  expect "gap limits affordable planned stop" ((details gap).planned_max > 0L);
  let eod = run ["rule_model","eod_trailing_marked_floor"; "fixed_floor_cents","";
                 "highest_eod_reference_cents","3050000"; "trailing_distance_cents","100000";
                 "floor_cap_cents","2900000"] in
  verdict "trailing floor cap" Research_review_only eod;
  let touch = run ["official_floor_cents","2985500"; "fixed_floor_cents","2985500";
                   "preservation_reserve_cents","0"] in
  verdict "touch floor inclusive" No_safe_contract_size touch;
  expect "one cent above liquidation" ((details touch).account_budget = 4499L);
  verdict "short" Research_review_only (run ["direction","short"; "stop_price_ticks","80080"]);
  verdict "setup" No_trade (run ["predefined_setup_eligible","false"]);
  verdict "no edge" No_validated_edge (run ["edge_review","insufficient"; "edge_review_source",""])

let test_adversarial () =
  List.iter (fun (name, changes) -> verdict name Data_unverified (run changes))
    [ "equity missing", ["marked_equity_cents",""];
      "floor unknown", ["official_floor_cents","unknown"];
      "mismatched account", ["rule_account_id","another"];
      "wrong equity", ["unrealized_cents","50"];
      "flat account with unrealized loss", ["unrealized_cents","-100"; "realized_since_inception_cents","-9900"];
      "wrong floor", ["fixed_floor_cents","2875000"];
      "wrong daily", ["gross_daily_headroom_cents","5000"];
      "unknown rule", ["rule_model","intraday_trailing"];
      "unsupported stage", ["stage","unknown"];
      "stale", ["account_observed_at_ms","1759999969999"];
      "future account", ["account_observed_at_ms","1760000000001"];
      "future observation", ["proposal_observed_at_ms","1760000000001"];
      "MNQ tick", ["reported_tick_value_cents","500"];
      "cross-product limits", ["limits_for_instrument","NQ"];
      "wrong direction", ["stop_price_ticks","80100"];
      "fraction", ["requested_contracts","1.5"];
      "fractional tick", ["entry_price_ticks","80000.3"];
      "unverified slippage", ["stress_slippage_ticks",""];
      "new shock", ["observed_adverse_slippage_ticks","3"];
      "wrap", ["round_trip_fees_per_contract_cents","9223372036854775807"];
      "check true size", ["requested_contracts","9223372036854775807"];
      "negative fee", ["other_costs_per_contract_cents","-1"];
      "open risk conflict", ["incremental_open_pending_downside_cents","500"];
      "unknown field", ["fee_instead","1"];
      "unverified source", ["provenance","unverified"];
      "unsupported month", ["contract_month","2025-10"];
      "roll mismatch", ["contract_month","2025-09"] ];
  verdict "duplicate field" Data_unverified
    (review ~as_of_ms:now ("instrument=NQ" :: lines roomy));
  List.iter (fun (name, status, changes) -> verdict name status (run changes))
    [ "firm max", Risk_blocked, ["firm_remaining_contracts","1"; "requested_contracts","2"];
      "no margin", No_safe_contract_size, ["buying_power_remaining_contracts","0"];
      "fees", No_safe_contract_size, ["fixed_round_trip_cost_cents","12000"];
      "open capacity", Account_at_risk, ["has_open_position_or_pending_order","true";
              "incremental_open_pending_downside_cents","90000"; "simultaneous_exposure_permitted","true"];
      "daily depleted", Risk_blocked, ["gross_daily_headroom_cents","0"; "session_start_equity_cents","3050000"];
      "third trade", Risk_blocked, ["trades_today","2"];
      "day lockout", Risk_blocked, ["day_trading_enabled","false"];
      "terminal", Account_at_risk, ["account_active","false"];
      "simultaneous", Risk_blocked, ["has_open_position_or_pending_order","true";
              "incremental_open_pending_downside_cents","10"] ];
  let open_case = run ["has_open_position_or_pending_order","true";
                       "incremental_open_pending_downside_cents","1000"; "simultaneous_exposure_permitted","true";
                       "gross_personal_daily_remaining_cents","5000"] in
  expect "open exposure also reserves personal capacity" ((details open_case).budget = 4000L)

(* Exhaust small cent-denominated budgets around whole-contract boundaries.
   Independent brute-force enumeration includes fixed costs only when qty > 0. *)
let test_integer_max () =
  for i = 0 to 200 do
    let budget = 47 * i in
    let r = run ["new_trade_ceiling_cents", string_of_int budget;
                 "fixed_round_trip_cost_cents","13"; "stop_price_ticks","79999"] in
    let s = details r in
    let expected = List.filter (fun q -> 13 + q * 550 <= budget) [1; 2] |> List.length in
    expect "integer maximum differs from enumeration" (Int64.to_int s.max_contracts = expected)
  done

let test_legacy_risk () =
  let signal = Some { Risk.direction = Risk.Long; observed_at_ms = now } in
  let a = { Risk.observed_at_ms = now; equity_cents = 100_000L;
            drawdown_floor_cents = 0L; day_net_cents = 0L; trades_today = 0;
            consecutive_losses = 0; open_contracts = 0 } in
  let p = { Risk.direction = Risk.Long; entry_ticks = 40; stop_ticks = 39; contracts = 101 } in
  let limits = { Risk.default_limits with max_contracts = 101; risk_per_trade_cents = 5000L;
                 round_trip_cost_cents_per_contract = 0L; slippage_ticks = 0 } in
  let blocked a p limits =
    match Risk.check ~now_ms:now ~session_open:true ~feed_healthy:true ~signal
            ~account:a ~proposal:p ~limits with Risk.Blocked _ -> true | _ -> false in
  expect "legacy risk must count all 101 requested contracts" (blocked a p limits);
  let single = { p with contracts = 1 } in
  expect "legacy fee wrap" (blocked a single { limits with round_trip_cost_cents_per_contract = Int64.max_int });
  expect "legacy negative floor" (blocked { a with drawdown_floor_cents = -1L } single limits);
  expect "legacy third trade" (blocked { a with trades_today = 2 } single { limits with max_trades_per_day = 10 });
  expect "legacy hard cap" (blocked a { single with entry_ticks = 500 } { limits with risk_per_trade_cents = 100_000L });
  expect "legacy inclusive daily touch" (blocked a single { limits with daily_stop_cents = 50L })

let () =
  test_legacy_risk (); test_values (); test_adversarial (); test_integer_max ();
  print_endline "Account survival contract, adversarial, and integer-boundary tests passed."
