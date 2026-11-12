(* First 50 holdout records against the Python engine's trade list. *)

let root_candidates =
  [
    "/workspace/trading-matrix/data/history";
    "data/history";
    "../data/history";
  ]

let find_root () =
  List.find_opt
    (fun root ->
      Sys.file_exists
        (Filename.concat root "futures/BTCUSDT/BTCUSDT-1m-2020-11.zip")
      && Sys.file_exists
           (Filename.concat root "aggTrades/BTCUSDT/BTCUSDT-aggTrades-2020-11.zip"))
    root_candidates

let cols line = String.split_on_char '\t' line

let () =
  let expect_path =
    match
      List.find_opt Sys.file_exists
        [ "expected_first50.txt"; "test/expected_first50.txt" ]
    with
    | Some p -> p
    | None ->
        prerr_endline "expected_first50.txt missing";
        exit 1
  in
  match find_root () with
  | None ->
      print_endline "skipped: holdout cache is not on this machine";
      exit 0
  | Some root ->
      let expected =
        let ic = open_in expect_path in
        let rows = ref [] in
        begin
          try
            while true do
              rows := input_line ic :: !rows
            done
          with End_of_file -> ()
        end;
        close_in ic;
        List.rev !rows
      in
      let summary =
        Scan.run ~root ~month_from:"2020-11" ~month_to:"2020-12" ~start_ms:(Scan.parse_day "2020-11-01")
          ~end_ms:(Scan.parse_day "2022-11-01") ()
      in
      let got = summary.Scan.records in
      if List.length got < List.length expected then failwith "fewer records than the Python list";
      List.iteri
        (fun i exp ->
          let r = List.nth got i in
          match cols exp with
          | time :: side :: outcome :: _ ->
              if
                r.Replay.Row.signal_time <> int_of_string time
                || r.Replay.Row.side <> side
                || r.Replay.Row.outcome <> outcome
              then
                failwith
                  (Printf.sprintf "trade %d ocaml %d %s %s python %s" i r.Replay.Row.signal_time r.Replay.Row.side
                     r.Replay.Row.outcome exp)
          | _ -> failwith "bad expected row")
        expected;
      print_endline "ok"
