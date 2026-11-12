# Supabase is ALREADY SET UP — do not recreate it

Project: trading-matrix (ref dkjwchtrrduraddkvhbh, region ap-south-1).
Connection values are in `.env`.

Already created by migration `matrix_core_schema`:
candles, rule_versions (row 1 = initial rules), predictions (incl. all
MEASUREMENT_FIX columns, track, setup_class, event_tag, blackout,
explain_simple, checkpoints, reasoning_embedding VECTOR(768)), lens_weights,
accuracy_stats, graduation_state, suggestions, reports, learner_math,
learner_glossary, learner_calls, view mobile_summary.

RLS is ON for every table. Anon key can only SELECT: predictions,
accuracy_stats, lens_weights, graduation_state, suggestions, reports,
mobile_summary. All writes use the service key from the backend only.
Realtime is enabled on predictions, suggestions, graduation_state.

Rules for build agents:
- Do NOT run supabase/schema.sql from scratch. Treat the live schema as the
  starting point. Any further change = a new numbered migration file in
  supabase/migrations/, documented in this file.
- Never put the service key in the Android app or any front-end code.
- Learner tables have no anon policies yet (single local user via backend).
  If the app must write learner data directly, propose Supabase Auth + RLS
  first and wait for approval.

## Migrations added by the Missions 1–8 / measurement-fix / backtest build

None. MEASUREMENT_FIX columns, `rule_versions`, and `graduation_state` are
already on the live project (see the list above). This build does not recreate
the project and does not run SQL against it. Backtest rows go to local SQLite
only (`backtest/*.sqlite`, gitignored), never to these tables.

`supabase/schema.sql` is a reference copy of the original spec plus the columns
the live project already has. It is not an instruction to execute.
