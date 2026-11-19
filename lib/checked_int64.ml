(** Exact arithmetic for cents and integral price ticks. Never wrap risk down. *)
exception Overflow

let add a b =
  if (b > 0L && a > Int64.sub Int64.max_int b)
     || (b < 0L && a < Int64.sub Int64.min_int b) then raise Overflow;
  Int64.add a b

let sub a b =
  if (b > 0L && a < Int64.add Int64.min_int b)
     || (b < 0L && a > Int64.add Int64.max_int b) then raise Overflow;
  Int64.sub a b

let mul_nonnegative a b =
  if a < 0L || b < 0L || (b > 0L && a > Int64.div Int64.max_int b)
  then raise Overflow;
  Int64.mul a b
