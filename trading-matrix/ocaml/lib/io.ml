(* Zip readers. unzip streams the archive; the month is not held as text. *)

let quote path = Filename.quote path

let open_zip path =
  let ic = Unix.open_process_in ("unzip -p " ^ quote path) in
  ic

let close_zip ic = ignore (Unix.close_process_in ic)

let is_digit c = c >= '0' && c <= '9'

let trim s =
  let len = String.length s in
  let rec l i =
    if i < len && (s.[i] = ' ' || s.[i] = '\r' || s.[i] = '\n' || s.[i] = '\t') then l (i + 1) else i
  in
  let rec r i =
    if i > 0 && (s.[i - 1] = ' ' || s.[i - 1] = '\r' || s.[i - 1] = '\n' || s.[i - 1] = '\t') then r (i - 1)
    else i
  in
  let a = l 0 in
  let b = r len in
  if a = 0 && b = len then s else String.sub s a (b - a)

let to_ms v = if v > 100_000_000_000_000 then v / 1000 else v

let read_klines path =
  let ic = open_zip path in
  let rows = ref [] in
  begin
    try
      while true do
        let line = trim (input_line ic) in
        if line <> "" && is_digit line.[0] then
          match String.split_on_char ',' line with
          | ts :: open_ :: high :: low :: close :: volume :: _ ->
              let candle =
                {
                  Formula.ts = to_ms (int_of_float (float_of_string ts));
                  open_ = float_of_string open_;
                  high = float_of_string high;
                  low = float_of_string low;
                  close = float_of_string close;
                  volume = float_of_string volume;
                }
              in
              rows := candle :: !rows
          | _ -> ()
      done
    with End_of_file -> ()
  end;
  close_zip ic;
  List.rev !rows

let read_funding path =
  let ic = open_zip path in
  let rows = ref [] in
  begin
    try
      while true do
        let line = trim (input_line ic) in
        if line <> "" && is_digit line.[0] then
          match String.split_on_char ',' line with
          | ts :: _ :: rate :: _ ->
              rows := (to_ms (int_of_float (float_of_string (trim ts))), float_of_string (trim rate)) :: !rows
          | _ -> ()
      done
    with End_of_file -> ()
  end;
  close_zip ic;
  !rows

type row = int * float * float * bool

type cursor = {
  ic : in_channel;
  mutable held : row option;
  mutable minute : int option;
  mutable eof : bool;
}

type minute = {
  buy : float;
  sell : float;
  minp : float option;
  maxp : float option;
  prices : (int * float) list;
  bins : (float * float) list;
}

let open_agg path = { ic = open_zip path; held = None; minute = None; eof = false }

let close_agg c = close_zip c.ic

let read c =
  match c.held with
  | Some row ->
      c.held <- None;
      Some row
  | None ->
      let rec loop () =
        match input_line c.ic with
        | exception End_of_file ->
            c.eof <- true;
            None
        | line ->
            if line = "" || not (is_digit line.[0]) then loop ()
            else
              match String.split_on_char ',' line with
              | _ :: price :: qty :: _ :: _ :: time :: maker :: _ ->
                  if maker = "" then loop ()
                  else
                    let raw = int_of_float (float_of_string (trim time)) in
                    let ch = maker.[0] in
                    let is_maker = ch = 't' || ch = 'T' || ch = '1' in
                    Some (to_ms raw, float_of_string price, float_of_string (trim qty), is_maker)
              | _ -> loop ()
      in
      loop ()

let peek c =
  match c.minute with
  | Some m -> Some m
  | None -> (
      match read c with
      | None -> None
      | Some ((ts, _, _, _) as row) ->
          c.held <- Some row;
          let m = ts - (ts mod 60_000) in
          c.minute <- Some m;
          Some m)

let consume c keep =
  match peek c with
  | None -> None
  | Some minute ->
      let buy = ref 0. in
      let sell = ref 0. in
      let lo = ref None in
      let hi = ref None in
      let prices = ref [] in
      let bins = Hashtbl.create 32 in
      let order = ref [] in
      let rec loop () =
        match read c with
        | None ->
            c.minute <- None;
            ()
        | Some ((ts, price, qty, maker) as row) ->
            let row_minute = ts - (ts mod 60_000) in
            if row_minute <> minute then begin
              c.held <- Some row;
              c.minute <- Some row_minute
            end
            else begin
              if maker then sell := !sell +. qty else buy := !buy +. qty;
              lo := Some (match !lo with None -> price | Some v -> min v price);
              hi := Some (match !hi with None -> price | Some v -> max v price);
              let key = Formula.tenth price in
              begin
                match Hashtbl.find_opt bins key with
                | Some q -> Hashtbl.replace bins key (q +. qty)
                | None ->
                    Hashtbl.add bins key qty;
                    order := key :: !order
              end;
              if keep then prices := (ts, price) :: !prices;
              loop ()
            end
      in
      loop ();
      if c.eof && c.held = None then c.minute <- None;
      (* !order is newest-first. Folding it conses the oldest key to the front. *)
      let bin_rows =
        List.fold_left (fun acc key -> (key, Hashtbl.find bins key) :: acc) [] !order
      in
      Some
        {
          buy = !buy;
          sell = !sell;
          minp = !lo;
          maxp = !hi;
          prices = List.rev !prices;
          bins = bin_rows;
        }
