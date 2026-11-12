(* WITH holdout scan. One position, closed candles, funding from the same months. *)

type summary = {
  blocked : int;
  wins : int;
  losses : int;
  timeouts : int;
  not_filled : int;
  counted : int;
  hit_rate : float;
  gross_mean : float;
  net_mean : float;
  net_x2 : float;
  records : Replay.Row.t list;
  seconds : float;
}

let is_leap y = (y mod 4 = 0 && y mod 100 <> 0) || y mod 400 = 0

let mdays y m =
  match m with
  | 1 | 3 | 5 | 7 | 8 | 10 | 12 -> 31
  | 4 | 6 | 9 | 11 -> 30
  | 2 -> if is_leap y then 29 else 28
  | _ -> invalid_arg "month"

let date_ms y m d =
  let days = ref 0 in
  for yy = 1970 to y - 1 do
    days := !days + if is_leap yy then 366 else 365
  done;
  for mm = 1 to m - 1 do
    days := !days + mdays y mm
  done;
  days := !days + (d - 1);
  !days * 86_400_000

let parse_day s =
  Scanf.sscanf s "%d-%d-%d" (fun y m d -> date_ms y m d)

let parse_month s = Scanf.sscanf s "%d-%d" (fun y m -> (y, m))

let months from_m to_m =
  let y1, m1 = parse_month from_m in
  let y2, m2 = parse_month to_m in
  let rec loop y m acc =
    if (y, m) > (y2, m2) then List.rev acc
    else
      let ny, nm = if m = 12 then (y + 1, 1) else (y, m + 1) in
      loop ny nm (Printf.sprintf "%04d-%02d" y m :: acc)
  in
  loop y1 m1 []

let price_path ts agg keep =
  match agg with
  | None -> []
  | Some a -> (
      match a.Io.minp with
      | None -> []
      | Some lo ->
          if keep && a.Io.prices <> [] then a.Io.prices
          else
            let rows = [ (ts, lo) ] in
            match a.Io.maxp with
            | Some hi when hi <> lo -> rows @ [ (ts + 1, hi) ]
            | _ -> rows)

let load_funding root from_m to_m =
  let rows =
    List.concat
      (List.map
         (fun month ->
           let path =
             Filename.concat root (Filename.concat "funding" (Filename.concat "BTCUSDT" ("BTCUSDT-fundingRate-" ^ month ^ ".zip")))
           in
           if Sys.file_exists path then Io.read_funding path else [])
         (months from_m to_m))
  in
  List.sort
    (fun (ta, ra) (tb, rb) ->
      let c = compare ta tb in
      if c <> 0 then c else compare ra rb)
    rows

let counted_n records =
  List.fold_left (fun n r -> if r.Replay.Row.counted then n + 1 else n) 0 records

let run ?(stop_after = 0) ~root ~month_from ~month_to ~start_ms ~end_ms () =
  let funding = load_funding root month_from month_to in
  let book = Book.create 0.0001 in
  let engine = Replay.create ~tick:0.10 ~spread:0.0001 ~funding in
  let blocked = ref 0 in
  let stop = ref false in
  let t0 = Unix.gettimeofday () in
  List.iter
    (fun month ->
      if not !stop then begin
        let kpath =
          Filename.concat root
            (Filename.concat "futures" (Filename.concat "BTCUSDT" ("BTCUSDT-1m-" ^ month ^ ".zip")))
        in
        if not (Sys.file_exists kpath) then failwith ("missing " ^ kpath);
        let candles = Io.read_klines kpath in
        let zpath =
          Filename.concat root
            (Filename.concat "aggTrades" (Filename.concat "BTCUSDT" ("BTCUSDT-aggTrades-" ^ month ^ ".zip")))
        in
        let cursor =
          if Sys.file_exists zpath && (Unix.stat zpath).Unix.st_size > 0 then Some (Io.open_agg zpath) else None
        in
        Fun.protect
          ~finally:(fun () -> match cursor with Some c -> Io.close_agg c | None -> ())
          (fun () ->
            List.iter
              (fun candle ->
                if not !stop then begin
                  let ts = candle.Formula.ts in
                  let keep = Replay.need_prices engine candle in
                  let agg =
                    match cursor with
                    | None -> None
                    | Some c ->
                        let rec skip () =
                          match Io.peek c with
                          | Some m when m < ts ->
                              ignore (Io.consume c false);
                              skip ()
                          | _ -> ()
                        in
                        skip ();
                        match Io.peek c with
                        | Some m when m = ts -> Io.consume c keep
                        | _ -> None
                  in
                  let buy, sell, bins =
                    match agg with
                    | None -> (0., 0., [])
                    | Some a -> (a.Io.buy, a.Io.sell, a.Io.bins)
                  in
                  let roles = Book.push book candle buy sell bins in
                  let path = price_path ts agg keep in
                  Replay.on_candle engine candle path;
                  let close_time = ts + 60_000 in
                  if start_ms <= close_time && close_time < end_ms then begin
                    if roles.Book.gate_blocked then incr blocked;
                    match (roles.Book.side_with, roles.Book.reward, roles.Book.risk, roles.Book.breakeven) with
                    | (("UP" | "DOWN") as side), Some reward, Some risk, Some _be ->
                        ignore
                          (Replay.open_setup engine ~direction:side ~price:roles.Book.close ~reward_pct:reward
                             ~risk_pct:risk ~signal_time:close_time)
                    | _ -> ()
                  end;
                  if stop_after > 0 && List.length (Replay.records engine) >= stop_after then stop := true
                end)
              candles);
        let recs = Replay.records engine in
        Printf.eprintf "  sentence %s blocked %d counted %d\n%!" month !blocked (counted_n recs)
      end)
    (months month_from month_to);
  let records =
    List.filter (fun r -> r.Replay.Row.signal_time >= start_ms && r.Replay.Row.signal_time < end_ms) (Replay.records engine)
  in
  let counted = List.filter (fun r -> r.Replay.Row.counted) records in
  let n = List.length counted in
  let nf = float_of_int n in
  let count outcome = List.length (List.filter (fun r -> r.Replay.Row.outcome = outcome) records) in
  let wins = count "WIN" in
  let losses = count "LOSS" in
  let timeouts = count "TIMEOUT" in
  let not_filled = count "NOT_FILLED" in
  let sum proj =
    List.fold_left
      (fun acc r ->
        acc
        +.
        match proj r with
        | Some v -> v
        | None -> 0.)
      0. counted
  in
  let gross_sum = sum (fun r -> r.Replay.Row.gross) in
  let net_sum = sum (fun r -> r.Replay.Row.net) in
  let x2_sum =
    List.fold_left
      (fun acc r ->
        let gross = match r.Replay.Row.gross with Some v -> v | None -> 0. in
        let cost = match r.Replay.Row.cost with Some v -> v | None -> 0. in
        acc +. (gross -. (2. *. cost) -. r.Replay.Row.funding))
      0. counted
  in
  {
    blocked = !blocked;
    wins;
    losses;
    timeouts;
    not_filled;
    counted = n;
    hit_rate = if n = 0 then 0. else float_of_int wins /. nf;
    gross_mean = if n = 0 then 0. else gross_sum /. nf;
    net_mean = if n = 0 then 0. else net_sum /. nf;
    net_x2 = if n = 0 then 0. else x2_sum /. nf;
    records;
    seconds = Unix.gettimeofday () -. t0;
  }
