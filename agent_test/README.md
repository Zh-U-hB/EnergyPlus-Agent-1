# Agent Robustness Benchmark — First-Pass IDF Success

`run_robustness_test.py` measures how reliably the EnergyPlus Agent can
produce a **runnable IDF in one shot** — i.e. with zero automatic
rollback rounds and no human intervention — across a corpus of building
description cases.

## Test corpus

Cases live under `agent_test/test_data/<mode>/<category>/<scale>/case_<NN>/testdata_prompt.json`.
Regenerate with `uv run python agent_test/gen_test_data.py` (90 cases,
grounded in DOE Commercial Reference Buildings / PNNL prototype models /
NIST TN 1765):

```
test_data/
└── text_only/                      # text-only mode (drawings not passed)
    ├── residential/{small,medium,large}/   # 10 cases each
    ├── office/{small,medium,large}/        # 10 cases each
    └── retail/{small,medium,large}/        # 10 cases each
```

Each `testdata_prompt.json` carries both the legacy numeric fields (area,
floors, zone counts) and a detailed free-text `Description` (footprint
dimensions, orientation, window-to-wall ratio, space layout) so the agent
has enough to build geometry without drawings.

## What "first-pass success" means

The agent graph validates cross-references in three places:
`cross_ref_foundations`, `cross_ref_complete`, and finally the `validate`
node. When `validate` finds errors **and** still has retries left
(`MAX_RETRIES = 2`), it performs **directed rollback** automatically and
re-runs the offending phase — *without* ever interrupting a human.

A case is a **first-pass success (一次成功)** only when **all** of these hold
(end-to-end definition):

1. On the **first** visit to the `validate` interrupt, cross-references are
   clean (zero errors) **and** `retry_count == 0` (the agent never rolled
   back). This is the pure modeling signal, recorded as `model_clean_first`.
2. We auto-approve, EnergyPlus actually runs, and produces a result artifact
   (`eplusout.end` / `eplusout.sql` / `eplustbl.csv`) — `simulation_ok`.
3. The resulting `eplusout.err` has **no Error-level lines** (no `** Fatal **`
   or `** Severe **`). `** Warning **` lines are tolerated and counted
   separately.

`first_pass = model_clean_first AND simulation_ok`. If the agent needed
rollback/rebuild but still produced a runnable IDF, we tag it
**`recovered`**; if it never ran cleanly, it's **`failed`**. Every case is
driven to completion regardless, so even failed cases have a full diagnostic
trail.

We report **two** success rates so you can tell where the loss happens:
- `first_pass_rate` — end-to-end (what you ultimately care about).
- `model_clean_first_rate` — pure modeling quality (clean first validate +
  no rollback), ignoring whether EnergyPlus accepted the IDF. A big gap
  between the two means "the agent built it correctly but the engine
  rejected it" (e.g. fatal geometry errors that cross-ref checks can't see).

## Why the human gate always approves

At the `validate` interrupt the harness **always returns `{"approved": True}`**,
even when errors are present. Two reasons:

- By the time the agent interrupts us, its *automatic* directed rollback is
  already exhausted, so the model is as good as it will get.
- **Rejection is a footgun here**: a rejected `{"approved": False, "feedback"}`
  routes the agent back to a full rebuild, and `validate_node` **resets
  `retry_count` to 0** on that path — which is *not* bounded by
  `MAX_RETRIES`. So rejecting on a persistent error can loop forever.

Approving lets every case reach the `simulate` node so we always get
`simulation_ok` / `recovered`, and a full diagnostic record.

## Metrics (per case)

| Field | Meaning |
|---|---|
| `first_pass` | END-TO-END: clean first model + no rollback + simulation OK with no Error-level err |
| `model_clean_first` | clean first validate (`first_validate_errors==0`) + `rollback_rounds==0` |
| `recovered` | needed rollback/rebuild but still simulated OK |
| `simulation_ok` | artifacts produced + `idf=` reported + err has no Fatal/Severe |
| `reached_validate` / `reached_simulate` | agent got this far |
| `rollback_rounds` | max `retry_count` at validate (= automatic rollback rounds) |
| `validate_hits` | how many times the validate interrupt fired |
| `rebuild_count` | how many times intake/revise re-ran (started over from the top) |
| `first_validate_errors` | cross-ref error count at the *first* validate hit |
| `cross_ref_errors_seen` | every error surfaced across all validate hits |
| `node_sequence` / `node_counts` | ordered node names + per-node execution counts |
| `node_timings` | ordered timeline of `{node, duration_s}` per node execution (incl. re-runs on rollback); find which agent phase is slow |
| `phase_total_s` | per-phase wall-clock totals (summed across re-runs), e.g. `{"surface": 45.3, ...}` |
| `phase_traces` | full per-phase tool-call log (`export_traces()`) |
| `phase_tool_stats` | per-phase aggregate: `{calls, succeeded, failed}` |
| `idf_path` / `output_files` | the IDF path + list of produced result artifacts |
| `err_fatal_count` / `err_severe_count` / `err_warning_count` | severity line counts in `eplusout.err` |
| `err_has_error_level` | True if any Fatal/Severe present |
| `elapsed_s` / `repeat_index` / `error` | wall time / which repetition / crash traceback |

The report also surfaces timing: `summary.json` carries `avg_phase_s`
(average wall-clock per phase, sorted slowest-first) and the per-run table
has a `slowest phase` column — useful to see at a glance whether surface
modelling, fenestration, or something else dominates agent time.

## Usage

> The agent calls an LLM and runs EnergyPlus, so `.env` and `energyplus`
> on `PATH` must be configured. Run with `uv run` to use the project env.

```bash
# all discovered cases (recursively, under agent_test/test_data/text_only)
uv run python agent_test/run_robustness_test.py

# --only accepts comma-separated PREFIXES against the relative-path case id:
#   --only residential            -> all residential (small/medium/large)
#   --only office/large           -> all large offices
#   --only retail/small/case_03   -> one case
#   --only residential,office/large
uv run python agent_test/run_robustness_test.py --only residential/small
uv run python agent_test/run_robustness_test.py --only office/large/case_03

# custom weather file
uv run python agent_test/run_robustness_test.py --epw data/weather/Shenzhen.epw

# pin the LLM sampling temperature for the whole run (robustness tests must
# be reproducible). The value is written into src/configs/llm.yaml and
# RESTORED on exit — it does NOT read DEFAULT_TEMPERATURE from .env.
uv run python agent_test/run_robustness_test.py --temperature 0.0

# run each case N times to measure per-case stability (a case that passes
# 3/5 times is "flaky"). Adds a "Per-case stability" table to the report.
uv run python agent_test/run_robustness_test.py --repeat 5 --temperature 0.0

# pass building drawings as multimodal input (needs a vision-capable LLM).
# OFF by default — the corpus is designed for text-only runs.
uv run python agent_test/run_robustness_test.py --images

# regenerate the test corpus (90 cases, grounded in DOE/NIST prototypes)
uv run python agent_test/gen_test_data.py

# custom test-data root (recursively scanned for testdata_prompt.json)
uv run python agent_test/run_robustness_test.py --data-root path/to/cases
```

### On `--temperature`

The phase agents each call `create_llm()` with no arguments, and
`create_llm` re-reads `src/configs/llm.yaml` on **every** call — there is no
shared LLM singleton to inject a config into. So the only way to pin the
sampling temperature for a whole benchmark is to edit the YAML before the
first agent runs. `set_llm_temperature()` does exactly that (regex on the
`temperature:` line) and `restore_llm_temperature()` puts it back, even if
the run crashes (it runs in a `try/finally`). The original value is also
captured into `summary.json` for reproducibility.

### On `--repeat`

Each `(case, repetition)` pair gets its own output dir
(`.../case_<rel>/rep_<i>/`) and its own `thread_id`, so repetitions are fully
independent. When `--repeat > 1`, `summary.json` gains a
`per_case_stability` block and the markdown report gains a stability table
showing `first_pass_count / repetitions` per case.

## Output

Everything is written under `agent_test/results/<timestamp>/` (one dated
folder per run, so multiple runs are easy to compare):

```
results/<timestamp>/                         # dated folder = one full run
├── results.json     # full per-(case, repetition) record (every metric)
├── summary.json     # aggregate stats + per_case_stability (when repeat>1)
├── report.md        # human-readable per-run + per-case-stability tables
└── <category>/<scale>/case_<NN>/            # MIRRORS the test-data tree
    └── rep_<i>/
        ├── run.log        # full per-run log
        ├── top_view.png   # 3-D isometric bird's-eye view of the produced IDF
        └── sim_out/       # EnergyPlus output (IDF, eplusout.*, eplustbl.csv, …)
```

The results tree mirrors the test-data tree (e.g. a case found at
`residential/large/case_03` writes its output to
`results/<ts>/residential/large/case_03/rep_0/`), so a per-category or
per-scale analysis is a simple directory walk.

### Bird's-eye view (top_view.png)

After each case's simulation, `agent_test/render_top_view.py` renders a
3-D isometric PNG of the produced IDF (surfaces colored by thermal zone)
alongside the run log. Rendering is best-effort: a failure only logs a
warning and never affects the test verdict. It loads
`src/results/idf_geometry.py` directly by file path (via importlib) to
avoid pulling in `idfpy`, which is slow to import in this environment.

## How it drives the agent

The script reuses the production entry points:

- `build_graph()` — fresh graph per case (isolates the `InMemorySaver`
  checkpointer so cases don't leak state).
- `run_session(graph, initial, context, config, on_interrupt, on_event)` —
  the same driver `main.py` uses, but with our own hooks:
  - `on_interrupt` = `CaseHarness.interrupt_handler`: auto-approves on a
    clean validate, auto-rejects with feedback on errors (so the agent
    still completes each case), and records the verdict.
  - `on_event`   = `CaseHarness.event_handler`: records the executed node
    sequence and the simulate node's message.

## Extending it

- **New cases** — drop a `<name>/testdata_prompt.json` (see existing
  files for the schema) into the data root; discovery is automatic.
- **Different verdict policy** — edit `CaseHarness.interrupt_handler`
  (e.g. always approve, or reject N times then give up).
- **More metrics** — add fields to `CaseResult` and fill them in
  `finalize()` / the hooks.
