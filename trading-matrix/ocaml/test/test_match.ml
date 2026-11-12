let tol = 1e-9

let near a b = abs_float (a -. b) <= tol

let fail msg = failwith msg

let read_sections path =
  let ic = open_in path in
  let table = Hashtbl.create 16 in
  let name = ref "" in
  let buf = ref [] in
  let flush () =
    if !name <> "" then Hashtbl.add table !name (List.rev !buf);
    buf := []
  in
  begin
    try
      while true do
        let line = input_line ic in
        if String.length line > 2 && line.[0] = '#' then begin
          flush ();
          name := String.trim (String.sub line 1 (String.length line - 1))
        end
        else buf := line :: !buf
      done
    with End_of_file -> ()
  end;
  flush ();
  close_in ic;
  table

let cols line = String.split_on_char '\t' line

let opt_float s = if s = "" then None else Some (float_of_string s)

let candle i =
  let ts = 1_604_188_800_000 + (i * 60_000) in
  let close = 10000.0 +. (float_of_int (i mod 50) *. 1.25) +. (float_of_int i *. 0.01) in
  {
    Formula.ts;
    open_ = close *. 0.999;
    high = close *. 1.002;
    low = close *. 0.998;
    close;
    volume = 1.0;
  }

let check_series name got expected =
  if List.length got <> List.length expected then
    fail (Printf.sprintf "%s length %d vs %d" name (List.length got) (List.length expected));
  List.iter2
    (fun g e ->
      match (g, e) with
      | None, None -> ()
      | Some a, Some b when near a b -> ()
      | Some a, Some b -> fail (Printf.sprintf "%s %g vs %g" name a b)
      | Some a, None -> fail (Printf.sprintf "%s extra %g" name a)
      | None, Some b -> fail (Printf.sprintf "%s missing %g" name b))
    got expected

let () =
  let path =
    let candidates = [ "fixture.txt"; "test/fixture.txt"; "ocaml/test/fixture.txt" ] in
    match List.find_opt Sys.file_exists candidates with
    | Some p -> p
    | None -> fail "fixture.txt not found"
  in
  let sections = read_sections path in
  let section name = Hashtbl.find sections name in
  let ema period =
    let t = Formula.ema period in
    List.init 1000 (fun i -> Formula.ema_push t (candle i).Formula.close)
  in
  let expect_ema name =
    List.map
      (fun line ->
        match cols line with
        | _ :: v :: _ -> opt_float v
        | _ -> None)
      (section name)
  in
  check_series "ema20" (ema 20) (expect_ema "ema20");
  check_series "ema50" (ema 50) (expect_ema "ema50");
  let atr =
    let t = Formula.wilder 8 in
    List.init 1000 (fun i ->
        let c = candle i in
        Formula.wilder_push t c.Formula.high c.Formula.low c.Formula.close)
  in
  let expect_atr =
    List.map
      (fun line -> match cols line with _ :: v :: _ -> opt_float v | _ -> None)
      (section "atr1")
  in
  check_series "atr1" atr expect_atr;
  let check_bars minutes name =
    let t = Formula.resampler minutes in
    let got =
      List.concat
        (List.init 1000 (fun i ->
             List.map
               (fun bar -> (bar.Formula.ts, bar.Formula.open_, bar.Formula.high, bar.Formula.low, bar.Formula.close))
               (Formula.resample_push t (candle i))))
    in
    let expected =
      List.map
        (fun line ->
          match cols line with
          | ts :: o :: h :: l :: c :: _ ->
              (int_of_string ts, float_of_string o, float_of_string h, float_of_string l, float_of_string c)
          | _ -> fail ("bad bar " ^ line))
        (section name)
    in
    if List.length got <> List.length expected then
      fail (Printf.sprintf "%s bars %d vs %d" name (List.length got) (List.length expected));
    List.iter2
      (fun (ts, o, h, l, c) (ets, eo, eh, el, ec) ->
        if ts <> ets || not (near o eo && near h eh && near l el && near c ec) then
          fail (Printf.sprintf "%s bar %d" name ts))
      got expected
  in
  check_bars 5 "bars5";
  check_bars 15 "bars15";
  List.iter
    (fun line ->
      match cols line with
      | name :: v :: _ -> (
          let got =
            match name with
            | "WIN" | "LOSS" | "TIMEOUT" | "NOT_FILLED" -> Formula.outcome_cost name 0.0001
            | "round_trip" -> Some (Formula.round_trip_cost 0.0001)
            | _ -> fail ("cost " ^ name)
          in
          let expected = opt_float v in
          match (got, expected) with
          | None, None -> ()
          | Some a, Some b when near a b -> ()
          | _ -> fail ("cost " ^ name))
      | _ -> fail "bad cost")
    (section "cost");
  List.iter
    (fun line ->
      match cols line with
      | price :: key :: _ ->
          let got = Formula.tenth (float_of_string price) in
          let expected = float_of_string key in
          if not (near got expected) then fail (Printf.sprintf "round %s -> %g vs %g" price got expected)
      | _ -> fail "bad round")
    (section "round");
  let trades = List.init 30 (fun i -> (100.0 +. (float_of_int i *. 0.1), float_of_int (((i * 3) mod 7) + 1))) in
  let expected_poc = float_of_string (List.hd (section "poc")) in
  let poc_ok =
    match Formula.poc trades 2.0 with
    | Some v -> near v expected_poc
    | None -> false
  in
  if not poc_ok then fail "poc";
  let book = Book.create 0.0001 in
  List.iteri
    (fun i line ->
      let c = candle i in
      let buy = if i mod 2 = 0 then 1.0 else 0.2 in
      let sell = if i mod 2 = 0 then 0.2 else 1.0 in
      let roles = Book.push book c buy sell [ (c.Formula.close, 1.0); (c.Formula.high, 0.5) ] in
      match cols line with
      | _ :: atr5 :: reward :: risk :: be :: blocked :: dead :: wide :: gov :: flow :: side :: rest ->
          let poc = match rest with p :: _ -> p | [] -> "" in
          let eq_opt a b =
            match (a, b) with
            | None, "" -> true
            | Some x, s -> near x (float_of_string s)
            | _ -> false
          in
          if
            (not (eq_opt (book.Book.atr5.Formula.value) atr5))
            || (not (eq_opt roles.Book.reward reward))
            || (not (eq_opt roles.Book.risk risk))
            || (not (eq_opt roles.Book.breakeven be))
            || (roles.Book.gate_blocked <> (blocked = "1"))
            || (roles.Book.dead <> (dead = "1"))
            || (roles.Book.wide <> (wide = "1"))
            || roles.Book.governor <> gov
            || roles.Book.doer <> flow
            || roles.Book.side_with <> side
            || not (eq_opt book.Book.prev_poc poc)
          then fail (Printf.sprintf "book candle %d" i)
      | _ -> fail (Printf.sprintf "bad book line %d" i))
    (section "book");
  print_endline "ok"
