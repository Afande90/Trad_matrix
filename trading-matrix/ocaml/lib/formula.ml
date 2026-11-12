(* Numeric pieces copied from the Python engine. Order of operations matches. *)

type candle = {
  ts : int;
  open_ : float;
  high : float;
  low : float;
  close : float;
  volume : float;
}

let maker_fee = 0.0002
let taker_fee = 0.0005
let slippage = 0.0001
let scalp_rr = 1.5
let min_reward_cost_ratio = 3.0
let max_breakeven_wr = 0.50
let dead_vol = 0.6

let python_round_int x =
  let neg = x < 0. in
  let ax = if neg then -.x else x in
  let fl = floor ax in
  let frac = ax -. fl in
  let ip =
    if frac > 0.5 then fl +. 1.
    else if frac < 0.5 then fl
    else if mod_float fl 2. = 0. then fl
    else fl +. 1.
  in
  let n = int_of_float ip in
  if neg then -n else n

let tenth price = float_of_int (python_round_int (price *. 10.)) /. 10.

let round_trip_cost spread = maker_fee +. maker_fee +. spread +. slippage

let outcome_cost outcome spread =
  match outcome with
  | "NOT_FILLED" -> None
  | "WIN" ->
      let extra = spread +. slippage in
      Some (maker_fee +. maker_fee +. extra)
  | "LOSS" | "TIMEOUT" ->
      let extra = spread +. slippage in
      Some (maker_fee +. taker_fee +. extra)
  | _ -> None

type gate = {
  blocked : bool;
  cost : float;
  reward : float;
  risk : float;
  breakeven : float;
}

let evaluate_cost_gate ~price ~atr ~avg_atr ~spread =
  let vol_ratio = if avg_atr = 0. then 0. else atr /. avg_atr in
  let blocked = ref false in
  if avg_atr > 0. && atr > 0. && vol_ratio < dead_vol then blocked := true;
  let cost = round_trip_cost spread in
  let reward = if price = 0. then 0. else scalp_rr *. atr /. price in
  let risk = if price = 0. then 0. else atr /. price in
  let denom = reward +. risk in
  let breakeven = if denom <= 0. then 1. else (risk +. cost) /. denom in
  if reward < min_reward_cost_ratio *. cost then blocked := true;
  if breakeven > max_breakeven_wr then blocked := true;
  { blocked = !blocked; cost; reward; risk; breakeven }

type ema = {
  period : int;
  alpha : float;
  mutable seed : float list;
  mutable value : float option;
}

let ema period =
  { period; alpha = 2.0 /. (float_of_int period +. 1.0); seed = []; value = None }

let ema_push t price =
  match t.value with
  | None ->
      t.seed <- t.seed @ [ price ];
      if List.length t.seed = t.period then
        t.value <- Some (List.fold_left ( +. ) 0. t.seed /. float_of_int t.period);
      t.value
  | Some v ->
      let next = (t.alpha *. price) +. ((1.0 -. t.alpha) *. v) in
      t.value <- Some next;
      t.value

type wilder = {
  period : int;
  alpha : float;
  mutable trs : float list;
  mutable prev : float option;
  mutable value : float option;
  mutable ntrs : int;
}

let wilder period =
  { period; alpha = 1.0 /. float_of_int period; trs = []; prev = None; value = None; ntrs = 0 }

let wilder_push t high low close =
  let tr =
    match t.prev with
    | None -> high -. low
    | Some prev ->
        max (high -. low) (max (abs_float (high -. prev)) (abs_float (low -. prev)))
  in
  t.prev <- Some close;
  t.trs <- tr :: t.trs;
  t.ntrs <- t.ntrs + 1;
  match t.value with
  | None ->
      if t.ntrs = t.period + 1 then begin
        (* trs is newest-first. Seed is trs[1 : period + 1] of the oldest-first list,
           which is the oldest `period` values after dropping the first TR. *)
        let oldest_first = List.rev t.trs in
        let rec drop n xs = if n <= 0 then xs else match xs with _ :: tl -> drop (n - 1) tl | [] -> [] in
        let rec take n xs acc =
          if n <= 0 then List.rev acc
          else match xs with h :: tl -> take (n - 1) tl (h :: acc) | [] -> List.rev acc
        in
        let used = take t.period (drop 1 oldest_first) [] in
        t.value <- Some (List.fold_left ( +. ) 0. used /. float_of_int t.period);
        t.trs <- []
      end;
      t.value
  | Some v ->
      let next = ((1.0 -. t.alpha) *. v) +. (t.alpha *. tr) in
      t.value <- Some next;
      t.value

type resampler = {
  ms : int;
  mutable current : candle option;
}

let resampler minutes = { ms = minutes * 60_000; current = None }

let resample_push t candle =
  let ts = candle.ts in
  let bucket = ts - (ts mod t.ms) in
  let emitted = ref [] in
  let emit bar = emitted := bar :: !emitted in
  begin
    match t.current with
    | Some cur when bucket <> cur.ts ->
        if ts >= cur.ts + t.ms then emit cur;
        t.current <- None
    | _ -> ()
  end;
  begin
    match t.current with
    | None ->
        t.current <-
          Some
            {
              ts = bucket;
              open_ = candle.open_;
              high = candle.high;
              low = candle.low;
              close = candle.close;
              volume = candle.volume;
            }
    | Some cur ->
        t.current <-
          Some
            {
              cur with
              high = max cur.high candle.high;
              low = min cur.low candle.low;
              close = candle.close;
              volume = cur.volume +. candle.volume;
            }
  end;
  begin
    match t.current with
    | Some cur when ts + 60_000 >= cur.ts + t.ms ->
        emit cur;
        t.current <- None
    | _ -> ()
  end;
  List.rev !emitted

let bracket direction entry reward risk =
  if direction = "UP" then (entry *. (1.0 +. reward), entry *. (1.0 -. risk))
  else (entry *. (1.0 -. reward), entry *. (1.0 +. risk))

let poc trades atr =
  if atr <= 0. || trades = [] then None
  else
    let bin = 0.1 *. atr in
    let table = Hashtbl.create 32 in
    let order = ref [] in
    List.iter
      (fun (price, qty) ->
        let idx = python_round_int (price /. bin) in
        match Hashtbl.find_opt table idx with
        | Some q -> Hashtbl.replace table idx (q +. qty)
        | None ->
            Hashtbl.add table idx qty;
            order := idx :: !order)
      trades;
    let keys = List.sort compare (List.rev !order) in
    let best_idx, _ =
      List.fold_left
        (fun (bi, bq) idx ->
          let q = Hashtbl.find table idx in
          if q > bq then (idx, q) else (bi, bq))
        (List.hd keys, -1.)
        keys
    in
    Some (float_of_int best_idx *. bin)
