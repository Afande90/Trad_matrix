(* EXTENDED maker replay. One position. Fill is a trade through by one tick. *)

module Row = struct
  type t = {
    signal_time : int;
    side : string;
    outcome : string;
    gross : float option;
    net : float option;
    cost : float option;
    funding : float;
    counted : bool;
  }
end

module Path = struct
  type t = {
    outcome : string;
    timeout_return : float;
    same_agg : int;
    same_loss : int;
  }
end

module Watch = struct
  type t = {
    direction : string;
    price : float;
    reward_pct : float;
    risk_pct : float;
    signal_time : int;
    mutable future : Formula.candle list;
    paths : (int, (int * float) list) Hashtbl.t;
    mutable filled : bool;
    mutable fill_index : int;
    mutable fill_checked : int;
    mutable record_written : bool;
    mutable actual_done : bool;
  }
end

type t = {
  tick : float;
  spread : float;
  max_hold : int;
  funding : (int * float) array;
  mutable watchers : Watch.t list;
  mutable records : Row.t list;
  mutable same_agg : int;
  mutable same_loss : int;
}

let create ~tick ~spread ~funding =
  {
    tick;
    spread;
    max_hold = 60;
    funding = Array.of_list funding;
    watchers = [];
    records = [];
    same_agg = 0;
    same_loss = 0;
  }

let hits (candle : Formula.candle) direction reward_px risk_px =
  if direction = "UP" then (candle.high >= reward_px, candle.low <= risk_px)
  else (candle.low <= reward_px, candle.high >= risk_px)

let first_touch trades direction reward_px risk_px =
  let rec loop = function
    | [] -> None
    | (_ts, price) :: rest ->
        if direction = "UP" then
          if price >= reward_px then Some "reward"
          else if price <= risk_px then Some "risk"
          else loop rest
        else if price <= reward_px then Some "reward"
        else if price >= risk_px then Some "risk"
        else loop rest
  in
  loop trades

let resolve direction entry reward risk candles max_hold paths =
  let reward_px, risk_px = Formula.bracket direction entry reward risk in
  let arr = Array.of_list candles in
  let n = Array.length arr in
  let held = min max_hold n in
  let exit_price = ref (if held = 0 then entry else arr.(held - 1).Formula.close) in
  let outcome = ref "TIMEOUT" in
  let same_agg = ref 0 in
  let same_loss = ref 0 in
  let broke = ref false in
  let i = ref 0 in
  while !i < held && not !broke do
    let candle = arr.(!i) in
    let hit_reward, hit_risk = hits candle direction reward_px risk_px in
    if hit_reward && hit_risk then begin
      let path = Hashtbl.find_opt paths candle.Formula.ts in
      match path with
      | None | Some [] ->
          outcome := "LOSS";
          exit_price := risk_px;
          incr same_loss;
          broke := true
      | Some trades ->
          incr same_agg;
          begin
            match first_touch trades direction reward_px risk_px with
            | Some "reward" ->
                outcome := "WIN";
                exit_price := reward_px
            | _ ->
                outcome := "LOSS";
                exit_price := risk_px
          end;
          broke := true
    end
    else if hit_reward then begin
      outcome := "WIN";
      exit_price := reward_px;
      broke := true
    end
    else if hit_risk then begin
      outcome := "LOSS";
      exit_price := risk_px;
      broke := true
    end;
    incr i
  done;
  if not !broke && held > 0 then exit_price := arr.(held - 1).Formula.close;
  let timeout_return = if entry = 0. then 0. else (!exit_price -. entry) /. entry in
  { Path.outcome = !outcome; timeout_return; same_agg = !same_agg; same_loss = !same_loss }

let through direction price trades tick =
  let rec loop = function
    | [] -> false
    | (_ts, px) :: rest ->
        if direction = "UP" && px <= price -. tick then true
        else if direction = "DOWN" && px >= price +. tick then true
        else loop rest
  in
  loop trades

let blocks (w : Watch.t) =
  if w.record_written && not (w.filled && not w.actual_done) then false
  else if w.filled && not w.actual_done then true
  else if (not w.filled) && w.fill_checked < 3 then true
  else false

let scalp_net outcome reward risk cost timeout direction =
  match outcome with
  | "NOT_FILLED" -> None
  | "WIN" -> Some (reward -. cost)
  | "LOSS" -> Some (-.(risk +. cost))
  | "TIMEOUT" ->
      let sign = if direction = "UP" then 1. else if direction = "DOWN" then -1. else 0. in
      Some ((sign *. timeout) -. cost)
  | _ -> None

let apply_funding funding direction candles =
  match candles with
  | [] -> 0.
  | first :: _ ->
      let entry_ts = first.Formula.ts in
      let last = List.nth candles (min (List.length candles) 60 - 1) in
      let exit_ts = last.Formula.ts + 60_000 in
      let sign = if direction = "UP" then 1. else -1. in
      let paid = ref 0. in
      Array.iter
        (fun (ts, rate) -> if entry_ts < ts && ts <= exit_ts then paid := !paid +. (sign *. rate))
        funding;
      !paid

let close_unfilled (engine : t) (w : Watch.t) (path : Path.t) =
  engine.same_agg <- engine.same_agg + path.same_agg;
  engine.same_loss <- engine.same_loss + path.same_loss;
  engine.records <-
    {
      Row.signal_time = w.signal_time;
      side = w.direction;
      outcome = "NOT_FILLED";
      gross = None;
      net = None;
      cost = None;
      funding = 0.;
      counted = false;
    }
    :: engine.records;
  w.record_written <- true

let advance (engine : t) (w : Watch.t) candle trades =
  w.future <- w.future @ [ candle ];
  if trades <> [] then Hashtbl.replace w.paths candle.Formula.ts trades;
  if (not w.filled) && w.fill_checked < 3 && through w.direction w.price trades engine.tick then begin
    w.filled <- true;
    w.fill_index <- List.length w.future - 1
  end;
  if w.fill_checked < 3 then w.fill_checked <- w.fill_checked + 1;
  let path = resolve w.direction w.price w.reward_pct w.risk_pct w.future engine.max_hold w.paths in
  let final = path.Path.outcome = "WIN" || path.Path.outcome = "LOSS" || List.length w.future >= engine.max_hold in
  if not final then ()
  else if (not w.filled) && w.fill_checked < 3 then ()
  else if not w.filled then close_unfilled engine w path
  else
    let actual_candles =
      let rec drop n xs =
        if n <= 0 then xs else match xs with _ :: tl -> drop (n - 1) tl | [] -> []
      in
      drop w.fill_index w.future
    in
    let actual_paths = Hashtbl.create 8 in
    List.iter
      (fun (c : Formula.candle) ->
        match Hashtbl.find_opt w.paths c.ts with
        | None -> ()
        | Some p -> Hashtbl.add actual_paths c.ts p)
      actual_candles;
    let actual =
      resolve w.direction w.price w.reward_pct w.risk_pct actual_candles engine.max_hold actual_paths
    in
    let actual_final =
      actual.Path.outcome = "WIN"
      || actual.Path.outcome = "LOSS"
      || List.length actual_candles >= engine.max_hold
    in
    if not actual_final then ()
    else begin
      engine.same_agg <- engine.same_agg + actual.Path.same_agg;
      engine.same_loss <- engine.same_loss + actual.Path.same_loss;
      let cost = Formula.outcome_cost actual.Path.outcome engine.spread in
      let net =
        match cost with
        | None -> None
        | Some cost ->
            scalp_net actual.Path.outcome w.reward_pct w.risk_pct cost actual.Path.timeout_return w.direction
      in
      let paid =
        if Array.length engine.funding = 0 then 0. else apply_funding engine.funding w.direction actual_candles
      in
      let net = match net with None -> None | Some n -> Some (n -. paid) in
      let gross =
        match (net, cost) with
        | Some n, Some c ->
            if actual.Path.outcome = "WIN" then Some w.reward_pct
            else if actual.Path.outcome = "LOSS" then Some (-.w.risk_pct)
            else Some (n +. paid +. c)
        | _ -> None
      in
      let outcome = actual.Path.outcome in
      engine.records <-
        {
          Row.signal_time = w.signal_time;
          side = w.direction;
          outcome;
          gross;
          net;
          cost;
          funding = paid;
          counted = outcome = "WIN" || outcome = "LOSS" || outcome = "TIMEOUT";
        }
        :: engine.records;
      w.record_written <- true;
      w.actual_done <- true
    end

let on_candle engine candle trades =
  List.iter (fun w -> if not w.Watch.record_written then advance engine w candle trades) engine.watchers;
  engine.watchers <- List.filter (fun w -> not w.Watch.record_written) engine.watchers

let open_setup engine ~direction ~price ~reward_pct ~risk_pct ~signal_time =
  if List.exists blocks engine.watchers then false
  else begin
    let w : Watch.t =
      {
        direction;
        price;
        reward_pct;
        risk_pct;
        signal_time;
        future = [];
        paths = Hashtbl.create 8;
        filled = false;
        fill_index = 0;
        fill_checked = 0;
        record_written = false;
        actual_done = false;
      }
    in
    engine.watchers <- engine.watchers @ [ w ];
    true
  end

let records engine = List.rev engine.records

let both_edges (w : Watch.t) (candle : Formula.candle) =
  let reward_px, risk_px = Formula.bracket w.direction w.price w.reward_pct w.risk_pct in
  if w.direction = "UP" then candle.high >= reward_px && candle.low <= risk_px
  else candle.low <= reward_px && candle.high >= risk_px

let need_prices engine candle =
  List.exists (fun w -> (not w.Watch.record_written) && both_edges w candle) engine.watchers
