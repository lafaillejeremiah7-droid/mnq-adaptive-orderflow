open Mnq_core

let expect cond msg = if not cond then failwith msg

let test_quotes () =
  let first =
    match Latest_quote.parse "6000000,100000" with
    | Ok q -> q
    | Error reason -> failwith reason
  in
  expect (Latest_quote.points first = 25000.0) "Wrong NQ futures price";
  let updated =
    match Latest_quote.parse "6001000,100001" with
    | Ok q -> q
    | Error reason -> failwith reason
  in
  expect
    (match Latest_quote.accept None first with
    | Ok (Some _) -> true
    | _ -> false)
    "First quote must be accepted";
  expect
    (match Latest_quote.accept (Some first) updated with
    | Ok (Some _) -> true
    | _ -> false)
    "Later quote must be accepted";
  expect
    (match Latest_quote.accept (Some first) first with
    | Error _ -> true
    | _ -> false)
    "Duplicate timestamp must reject";
  expect
    (match Latest_quote.accept (Some updated) first with
    | Error _ -> true
    | _ -> false)
    "Stale quote must reject";
  List.iter
    (fun row ->
      expect
        (match Latest_quote.parse row with
        | Error _ -> true
        | _ -> false)
        ("Invalid NQ quote accepted: " ^ row))
    [
      "6000001,100000";
      "-1000,100000";
      "6000000,0";
      "6000000,notprice";
      "6000000,100000,7";
      "";
    ]

let () = test_quotes (); print_endline "Latest NQ quote tests passed"
