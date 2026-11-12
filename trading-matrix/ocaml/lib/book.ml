(* SentenceBook.push, in the Python order. *)

type roles = {
  close : float;
  governor : string;
  doer : string;
  reward : float option;
  risk : float option;
  breakeven : float option;
  gate_blocked : bool;
  dead : bool;
  wide : bool;
  side_with : string;
}

type t = {
  spread : float;
  m15 : Formula.resampler;
  m5 : Formula.resampler;
  ema20 : Formula.ema;
  ema50 : Formula.ema;
  atr1 : Formula.wilder;
  atr5 : Formula.wilder;
  mutable atr1_window : float list;
  mutable atr5_now : float option;
  mutable governor_side : string;
  mutable flow : (float * float) list;
  mutable day : string option;
  mutable day_high : float option;
  mutable day_low : float option;
  bins : (float, float) Hashtbl.t;
  mutable bin_order : float list;
  mutable day_atr : float option;
  mutable prev_high : float option;
  mutable prev_low : float option;
  mutable prev_poc : float option;
}

let day_of ts =
  let tm = Unix.gmtime (float_of_int (ts / 1000)) in
  Printf.sprintf "%04d-%02d-%02d" (tm.tm_year + 1900) (tm.tm_mon + 1) tm.tm_mday

let create spread =
  {
    spread;
    m15 = Formula.resampler 15;
    m5 = Formula.resampler 5;
    ema20 = Formula.ema 20;
    ema50 = Formula.ema 50;
    atr1 = Formula.wilder 8;
    atr5 = Formula.wilder 8;
    atr1_window = [];
    atr5_now = None;
    governor_side = "";
    flow = [];
    day = None;
    day_high = None;
    day_low = None;
    bins = Hashtbl.create 4096;
    bin_order = [];
    day_atr = None;
    prev_high = None;
    prev_low = None;
    prev_poc = None;
  }

let add_bin t price qty =
  match Hashtbl.find_opt t.bins price with
  | Some q -> Hashtbl.replace t.bins price (q +. qty)
  | None ->
      Hashtbl.add t.bins price qty;
      t.bin_order <- price :: t.bin_order

let freeze t =
  (* bin_order is newest-first. Folding it yields oldest-first, matching dict insertion. *)
  let trades =
    List.fold_left
      (fun acc price ->
        let qty = Hashtbl.find t.bins price in
        if qty > 0. then (price, qty) :: acc else acc)
      [] t.bin_order
  in
  t.prev_high <- t.day_high;
  t.prev_low <- t.day_low;
  t.prev_poc <- Formula.poc trades (match t.day_atr with Some v -> v | None -> 0.);
  t.day_high <- None;
  t.day_low <- None;
  Hashtbl.clear t.bins;
  t.bin_order <- [];
  t.day_atr <- None

let governor ema20 ema50 close =
  match (ema20, ema50) with
  | Some fast, Some slow ->
      if fast > slow && close > slow then "UP"
      else if fast < slow && close < slow then "DOWN"
      else ""
  | _ -> ""

let doer buy sell =
  let total = buy +. sell in
  if total <= 0. then ""
  else
    let share = buy /. total in
    if share >= 0.60 then "BUYERS" else if share <= 0.40 then "SELLERS" else ""

let target_near close atr levels =
  match atr with
  | None -> false
  | Some atr when atr <= 0. || levels = [] -> false
  | Some atr ->
      let span = 0.25 *. atr in
      List.exists (fun level -> abs_float (close -. level) <= span) levels

let exception_veto range atr =
  match atr with
  | None -> true
  | Some atr when atr <= 0. -> true
  | Some atr -> range > 3.0 *. atr

let side_with ~target ~state ~wide ~governor ~doer =
  if not target then ""
  else if not state then ""
  else if wide then ""
  else if governor <> "UP" && governor <> "DOWN" then ""
  else if governor = "UP" && doer <> "BUYERS" then ""
  else if governor = "DOWN" && doer <> "SELLERS" then ""
  else governor

let push t candle buy sell trades =
  let day = day_of candle.Formula.ts in
  begin
    match t.day with
    | None -> t.day <- Some day
    | Some prev when prev <> day ->
        freeze t;
        t.day <- Some day
    | Some _ -> ()
  end;
  let high = candle.Formula.high in
  let low = candle.Formula.low in
  let close = candle.Formula.close in
  t.day_high <- Some (match t.day_high with None -> high | Some v -> max v high);
  t.day_low <- Some (match t.day_low with None -> low | Some v -> min v low);
  List.iter (fun (price, qty) -> add_bin t price qty) trades;
  let atr1 = Formula.wilder_push t.atr1 high low close in
  begin
    match atr1 with
    | None -> ()
    | Some v ->
        t.atr1_window <- t.atr1_window @ [ v ];
        if List.length t.atr1_window > 10 then
          t.atr1_window <- List.tl t.atr1_window
  end;
  List.iter
    (fun bar ->
      match Formula.wilder_push t.atr5 bar.Formula.high bar.Formula.low bar.Formula.close with
      | None -> ()
      | Some updated -> t.atr5_now <- Some updated)
    (Formula.resample_push t.m5 candle);
  begin
    match t.atr5_now with
    | None -> ()
    | Some v -> t.day_atr <- Some v
  end;
  List.iter
    (fun bar ->
      let fast = Formula.ema_push t.ema20 bar.Formula.close in
      let slow = Formula.ema_push t.ema50 bar.Formula.close in
      t.governor_side <- governor fast slow bar.Formula.close)
    (Formula.resample_push t.m15 candle);
  t.flow <- t.flow @ [ (buy, sell) ];
  if List.length t.flow > 3 then t.flow <- List.tl t.flow;
  let bought = List.fold_left (fun acc (b, _) -> acc +. b) 0. t.flow in
  let sold = List.fold_left (fun acc (_, s) -> acc +. s) 0. t.flow in
  let flow_side = doer bought sold in
  let levels =
    List.fold_right
      (fun v acc -> match v with None -> acc | Some x -> x :: acc)
      [ t.prev_high; t.prev_low; t.prev_poc ]
      []
  in
  let atr5 = t.atr5_now in
  let gate_blocked = ref true in
  let reward = ref None in
  let risk = ref None in
  let breakeven = ref None in
  begin
    match atr5 with
    | Some atr when atr > 0. && close > 0. ->
        let gate = Formula.evaluate_cost_gate ~price:close ~atr ~avg_atr:atr ~spread:t.spread in
        gate_blocked := gate.Formula.blocked;
        reward := Some gate.Formula.reward;
        risk := Some gate.Formula.risk;
        breakeven := Some gate.Formula.breakeven
    | _ -> ()
  end;
  let dead =
    match atr1 with
    | Some atr when List.length t.atr1_window >= 10 ->
        let avg = List.fold_left ( +. ) 0. t.atr1_window /. float_of_int (List.length t.atr1_window) in
        avg <= 0. || atr /. avg < 0.6
    | _ -> true
  in
  let wide = exception_veto (high -. low) atr1 in
  let near = target_near close atr5 levels in
  let state = (not !gate_blocked) && not dead in
  {
    close;
    governor = t.governor_side;
    doer = flow_side;
    reward = !reward;
    risk = !risk;
    breakeven = !breakeven;
    gate_blocked = !gate_blocked;
    dead;
    wide;
    side_with = side_with ~target:near ~state ~wide ~governor:t.governor_side ~doer:flow_side;
  }
