let root = ref "/workspace/trading-matrix/data/history"
let month_from = ref "2020-11"
let month_to = ref "2022-10"
let start_day = ref "2020-11-01"
let end_day = ref "2022-11-01"
let trades_out = ref ""
let stop_after = ref 0

let () =
  Arg.parse
    [
      ("--root", Arg.Set_string root, "history root");
      ("--from", Arg.Set_string month_from, "first month YYYY-MM");
      ("--to", Arg.Set_string month_to, "last month YYYY-MM");
      ("--start", Arg.Set_string start_day, "inclusive UTC day");
      ("--end", Arg.Set_string end_day, "exclusive UTC day");
      ("--trades", Arg.Set_string trades_out, "write records here");
      ("--stop-after", Arg.Set_int stop_after, "stop after this many records");
    ]
    (fun _ -> ())
    "holdout";
  let summary =
    Scan.run ~stop_after:!stop_after ~root:!root ~month_from:!month_from ~month_to:!month_to
      ~start_ms:(Scan.parse_day !start_day) ~end_ms:(Scan.parse_day !end_day) ()
  in
  if !trades_out <> "" then begin
    let oc = open_out !trades_out in
    List.iter
      (fun r ->
        Printf.fprintf oc "%d\t%s\t%s\t%s\t%s\t%s\t%.17g\n" r.Replay.Row.signal_time r.Replay.Row.side r.Replay.Row.outcome
          (match r.Replay.Row.gross with None -> "" | Some v -> Printf.sprintf "%.17g" v)
          (match r.Replay.Row.net with None -> "" | Some v -> Printf.sprintf "%.17g" v)
          (match r.Replay.Row.cost with None -> "" | Some v -> Printf.sprintf "%.17g" v)
          r.Replay.Row.funding)
      summary.Scan.records;
    close_out oc
  end;
  Printf.printf "counted %d\n" summary.Scan.counted;
  Printf.printf "wins %d\n" summary.Scan.wins;
  Printf.printf "losses %d\n" summary.Scan.losses;
  Printf.printf "timeouts %d\n" summary.Scan.timeouts;
  Printf.printf "not_filled %d\n" summary.Scan.not_filled;
  Printf.printf "blocked %d\n" summary.Scan.blocked;
  Printf.printf "hit_rate %.17g\n" summary.Scan.hit_rate;
  Printf.printf "gross_mean %.17g\n" summary.Scan.gross_mean;
  Printf.printf "net_mean %.17g\n" summary.Scan.net_mean;
  Printf.printf "net_x2 %.17g\n" summary.Scan.net_x2;
  Printf.printf "seconds %.3f\n" summary.Scan.seconds
