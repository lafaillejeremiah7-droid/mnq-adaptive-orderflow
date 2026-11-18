(** Volume at price, separated by aggressor side. Integer tick prices. *)

module Price_map = Map.Make (Int)

type level = { buy : int; sell : int }
type t = level Price_map.t

type value_area = {
  poc_ticks : int;
  val_ticks : int;
  vah_ticks : int;
  total_volume : int;
}

let empty = Price_map.empty

let add_trade profile (trade : Market.trade) =
  let previous =
    match Price_map.find_opt trade.price_ticks profile with
    | None -> { buy = 0; sell = 0 }
    | Some level -> level
  in
  let updated =
    match trade.aggressor with
    | Market.Buyer -> { previous with buy = previous.buy + trade.quantity }
    | Market.Seller -> { previous with sell = previous.sell + trade.quantity }
  in
  Price_map.add trade.price_ticks updated profile

let delta profile =
  Price_map.fold (fun _ level sum -> sum + level.buy - level.sell) profile 0

let total_volume profile =
  Price_map.fold (fun _ level sum -> sum + level.buy + level.sell) profile 0

(** Expand outward from the highest-volume tick until >= 70% is covered.
    Ties resolve to the lower price, then to the lower side of expansion.
    Missing tick levels are included in the price interval with zero volume.
    This is one explicit convention, not a promise to match Tradovate. *)
let value_area profile =
  let levels =
    Price_map.bindings profile
    |> List.map (fun (tick, level) -> (tick, level.buy + level.sell))
    |> List.filter (fun (_, volume) -> volume > 0)
    |> Array.of_list
  in
  let n = Array.length levels in
  if n = 0 then None
  else
    let total = Array.fold_left (fun sum (_, volume) -> sum + volume) 0 levels in
    let poc = ref 0 in
    for i = 1 to n - 1 do
      let _, current_volume = levels.(i) in
      let _, highest_volume = levels.(!poc) in
      if current_volume > highest_volume then poc := i
    done;
    let rec expand low high covered =
      if covered * 10 >= total * 7 || (low = 0 && high = n - 1) then
        (low, high)
      else
        let left_volume = if low > 0 then snd levels.(low - 1) else -1 in
        let right_volume =
          if high + 1 < n then snd levels.(high + 1) else -1
        in
        if left_volume >= right_volume then
          expand (low - 1) high (covered + left_volume)
        else
          expand low (high + 1) (covered + right_volume)
    in
    let low, high = expand !poc !poc (snd levels.(!poc)) in
    Some
      {
        poc_ticks = fst levels.(!poc);
        val_ticks = fst levels.(low);
        vah_ticks = fst levels.(high);
        total_volume = total;
      }
