#!/usr/bin/env python3
"""EnergyPlus Agent — multi-case robustness (first-pass IDF success) benchmark.

Goal
----
Measure how reliably the agent can produce a *runnable* EnergyPlus IDF
in **one shot** — i.e. with **zero auto-rollback rounds** and no human
intervention — across a set of building description cases.

What "first-pass success" means here
------------------------------------
The agent graph validates cross-references in two places
(`cross_ref_foundations`, `cross_ref_complete`) and once more inside the
`validate` node, which performs *directed rollback* automatically up to
``MAX_RETRIES`` (=2) rounds before it ever interrupts a human.

We therefore count a case as a **first-pass success (一次成功)** only if
ALL of the following hold:

1. The validate interrupt fires with **no cross-ref errors** AND
   ``retry_count == 0`` (the agent never rolled back).
2. We auto-approve, the simulation actually runs, and EnergyPlus exits 0
   (a ``*.idf`` + ``eplusout.end`` / ``eplusout.sql`` is produced).

If the validate interrupt has errors or retry_count > 0, we still let the
agent keep going (auto-approve or auto-reject) so it completes the case,
but the run is recorded as **not** first-pass (we tag it ``recovered`` if
it still simulates OK, or ``failed`` if it does not).

Metrics recorded per case
-------------------------
- ``first_pass``            : bool — did it succeed with 0 rollbacks?
- ``recovered``             : bool — needed rollback but still simulated OK.
- ``simulation_ok``         : bool — EnergyPlus exit code 0 + output files.
- ``rollback_rounds``       : int — how many validate-node rollback rounds ran.
- ``cross_ref_errors_seen`` : list[str] — every error ever surfaced at validate.
- ``node_sequence``         : list[str] — ordered node names actually executed
                                          (driven by the ``on_event`` hook).
- ``phase_traces``          : dict  — per-phase tool-call log from
                                       ``export_traces()`` (name/args/success).
- ``elapsed_s``             : float — wall-clock for the whole case.
- ``error``                 : str|None — if the case crashed unexpectedly.

Outputs
-------
- ``agent_test/results/<timestamp>/results.json``  — full per-case record.
- ``agent_test/results/<timestamp>/summary.json``  — aggregate stats.
- ``agent_test/results/<timestamp>/report.md``     — human-readable table.
- ``agent_test/results/<timestamp>/*.log``         — one log per case.

NOTE: This script does NOT run itself automatically. Execute it manually:

    python agent_test/run_robustness_test.py            # all cases
    python agent_test/run_robustness_test.py --only 0,2,11
    python agent_test/run_robustness_test.py --epw data/weather/Shenzhen.epw
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# --- Make the repo root importable so `from src...` works from any CWD ---
# Script lives at <repo>/agent_test/run_robustness_test.py, so parents[1]
# is the repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
assert (REPO_ROOT / "src").is_dir(), f"REPO_ROOT miscomputed: {REPO_ROOT}"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from langchain_core.runnables import RunnableConfig
from loguru import logger

from src.agent import AgentState, SimContext, build_graph
from src.agent.runner import run_session
from src.agent.trace import export_traces, reset_traces

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
TEST_DATA_ROOT = REPO_ROOT / "agent_test" / "test_data" / "text_only"
DEFAULT_EPW = REPO_ROOT / "data" / "weather" / "Shenzhen.epw"
RESULTS_DIR = REPO_ROOT / "agent_test" / "results"

# The validate interrupt payload keys we read (see validate_node + runner).
INTERRUPT_KEYS = ("summary", "errors", "message")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class CaseResult:
    """Everything we record about a single case run.

    "First-pass success" (first_pass) is the END-TO-END definition:
    the agent built a usable IDF in one shot AND EnergyPlus actually ran
    it without Error-level messages. See ``finalize()``.
    """

    case_id: str
    case_name: str = ""
    prompt_json: str = ""
    repeat_index: int = 0  # which repetition of this case (0-based)

    # --- core verdicts ---
    first_pass: bool = False        # 首次建模零错误 + 零回滚 + 模拟可跑通(无 Error 级)
    model_clean_first: bool = False  # 首次到 validate 时交叉引用零错误(纯建模口径)
    recovered: bool = False         # 回滚过/首次有错,但最终跑通
    simulation_ok: bool = False     # EnergyPlus 退出码 0 + 有输出 + err 无 Error 级
    reached_validate: bool = False
    reached_simulate: bool = False

    # --- validate / rollback diagnostics ---
    rollback_rounds: int = 0        # max retry_count seen at validate (=自动回滚轮数)
    validate_hits: int = 0          # validate 关卡被触发(interrupt)的总次数
    rebuild_count: int = 0          # intake/revise 重新执行的次数(=从入口重做了几遍)
    first_validate_errors: int = 0  # 首次到 validate 关卡时的交叉引用错误数
    cross_ref_errors_seen: list[str] = field(default_factory=list)
    validate_summary: dict | None = None

    # --- node execution diagnostics ---
    node_sequence: list[str] = field(default_factory=list)  # 按真实执行顺序的节点名
    node_counts: dict[str, int] = field(default_factory=dict)  # 每个节点执行了几次
    # Per-node wall-clock timing timeline (ordered). Each entry is
    # {"node": <name>, "duration_s": <float>} for one execution; a node that
    # re-runs on rollback appears twice. Lets us see how long each agent
    # phase (intake/zone/.../simulate/analyze) actually took.
    node_timings: list[dict[str, Any]] = field(default_factory=list)
    # Aggregated per-phase totals (sum across re-runs), e.g.
    # {"surface": 45.3, "intake": 12.1, ...} — handy to find the slow phase.
    phase_total_s: dict[str, float] = field(default_factory=dict)

    # --- per-phase tool-call diagnostics (from export_traces) ---
    phase_traces: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    phase_tool_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    # e.g. {"zone": {"calls": 12, "succeeded": 11, "failed": 1}}

    # --- simulation / output diagnostics ---
    idf_path: str | None = None
    output_files: list[str] = field(default_factory=list)  # 磁盘上的 eplusout.* 清单
    err_fatal_count: int = 0
    err_severe_count: int = 0
    err_warning_count: int = 0
    err_has_error_level: bool = False  # Fatal 或 Severe 之一出现 -> True

    # --- misc ---
    elapsed_s: float = 0.0
    error: str | None = None
    simulate_message: str | None = None


# ---------------------------------------------------------------------------
# Test-case discovery / prompt construction
# ---------------------------------------------------------------------------
def discover_cases(root: Path = TEST_DATA_ROOT) -> list[dict[str, Any]]:
    """Recursively load every ``testdata_prompt.json`` under ``root``.

    Supports nested directories (e.g. ``text_only/residential/large/case_03``).
    Each returned item is::

        {"id": <rel path str>, "data": <json dict>, "_dir": <abs path>,
         "category": <str|None>, "scale": <str|None>}

    The ``id`` is the case directory's path relative to ``root`` in POSIX
    form (e.g. ``"residential/large/case_03"``), which is unique across the
    whole tree and lets ``--only`` do prefix matching. ``category`` and
    ``scale`` are sliced from the first two path segments when present, so
    the report can aggregate per building-type / scale.
    """
    cases: list[dict[str, Any]] = []
    for p in sorted(root.rglob("testdata_prompt.json")):
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        rel = p.parent.relative_to(root)
        cid = rel.as_posix()  # e.g. "residential/large/case_03"
        parts = rel.parts
        category = parts[0] if len(parts) >= 1 else None
        scale = parts[1] if len(parts) >= 2 else None
        cases.append(
            {
                "id": cid,
                "data": data,
                "_dir": str(p.parent.resolve()),
                "category": category,
                "scale": scale,
            }
        )
    return cases


def build_user_prompt(case: dict[str, Any]) -> str:
    """Turn a testdata_prompt.json into a natural-language building description.

    The agent's intake node expects free-form text + optional images. We
    render the structured JSON fields into a compact English description so
    the same prompt works regardless of the LLM language setting.

    Both the legacy numeric fields and the extended descriptive fields
    (footprint, orientation, layout, ...) are supported; if a rich
    ``Description`` block is present it is appended verbatim.
    """
    d = case["data"]
    name = d.get("TestName") or f"building_{case['id']}"
    loc = d.get("Building location", "Shenzhen")
    btype = d.get("Building type", "Office")
    area = d.get("Floor area", "")
    floors = d.get("Number of floors", "")
    zpf = d.get("Number of thermal zones per floor of the building", "")
    ztot = d.get("Number of total thermal zones in the building", "")

    lines = [
        "Please build an EnergyPlus IDF model for the following building.",
        f"- Name: {name}",
        f"- Location: {loc}",
        f"- Building type: {btype}",
    ]
    if area:
        lines.append(f"- Total floor area: {area}")
    if floors:
        lines.append(f"- Number of floors: {floors}")
    if zpf:
        lines.append(f"- Thermal zones per floor: {zpf}")
    if ztot:
        lines.append(f"- Total thermal zones: {ztot}")
    # Extended descriptive fields (text-only corpus). All optional.
    for label, key in (
        ("- Footprint width (east-west, m)", "Footprint width (east-west, m)"),
        ("- Footprint depth (north-south, m)", "Footprint depth (north-south, m)"),
        ("- Floor-to-floor height (m)", "Floor-to-floor height (m)"),
        ("- Orientation (deg from north)", "Orientation (degrees from north)"),
        ("- Window-to-wall ratio", "Window-to-wall ratio"),
        ("- Space layout", "Space layout"),
    ):
        val = d.get(key)
        if val:
            lines.append(f"{label}: {val}")
    # If a full prose description is provided, append it verbatim — it is the
    # richest single source of modelling guidance for text-only runs.
    desc = d.get("Description")
    if desc:
        lines.append("")
        lines.append(desc.strip())
    else:
        lines.append(
            "Create all zones, materials, constructions, surfaces, fenestrations, "
            "HVAC (ideal loads), people, lights and schedules so the resulting "
            "IDF can run in EnergyPlus without errors. "
            "Derive the zone layout and geometry from the counts above; keep the "
            "footprint rectangular and dimensions reasonable for the stated area."
    )
    return "\n".join(lines)


def collect_images(case: dict[str, Any]) -> list[str]:
    """Collect the (optional) drawing paths declared in the prompt JSON."""
    d = case["data"]
    keys = (
        "Top view path of the building",
        "Front view path of the building",
        "Building side view path",
        "Path of the supplementary plan example drawing for the building",
    )
    imgs: list[str] = []
    for k in keys:
        v = d.get(k, "")
        if not v:
            continue
        # JSON paths are repo-root-relative; resolve & existence-check.
        p = Path(v)
        if not p.is_absolute():
            p = REPO_ROOT / p
        if p.exists():
            imgs.append(str(p))
        else:
            logger.warning("[{}] image not found, skipping: {}", case["id"], v)
    return imgs


# ---------------------------------------------------------------------------
# Interrupt + event hooks (the heart of the measurement)
# ---------------------------------------------------------------------------
class CaseHarness:
    """Per-case state machine that drives run_session and records metrics.

    - ``interrupt_handler`` is what validate calls; we auto-decide and record.
    - ``event_handler``    records the executed node sequence.
    """

    def __init__(self, case: dict[str, Any], output_dir: Path, repeat_index: int = 0) -> None:
        self.case = case
        self.output_dir = output_dir
        self.result = CaseResult(
            case_id=case["id"],
            prompt_json=str(case["_dir"]),
            repeat_index=repeat_index,
        )
        self.result.case_name = case["data"].get("TestName", "")

        self._validated_count = 0          # how many times validate fired
        self._first_errors: list[str] = []
        self._first_summary: dict | None = None
        self._approved = False
        # Wall-clock anchor for per-node timing. Anchored at harness creation
        # (~case start) so even the FIRST node (intake) gets a duration =
        # first_callback_time - harness_creation_time.
        self._last_node_t: float = time.perf_counter()

    # ---- interrupt handler (validate) ----
    def interrupt_handler(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record the validate verdict and ALWAYS approve (let the case run).

        Why always-approve: the agent performs *automatic* directed rollback
        before it ever reaches this human gate, so by the time it interrupts
        us the model is as good as it will get. Rejecting here would send
        the agent back to a full rebuild, which **resets retry_count**
        (validate_node sets it to 0 on rejection) and is NOT bounded by
        MAX_RETRIES — i.e. it can loop forever if the same error persists.

        "First-pass success" is therefore decided purely by the *first*
        validate hit (errors == 0 AND retry_count == 0), recorded below —
        not by whether we approve here. Approving lets every case reach the
        simulate node so we can also measure ``simulation_ok`` / ``recovered``.
        """
        self._validated_count += 1
        self.result.validate_hits = self._validated_count
        self.result.reached_validate = True

        errors = list(payload.get("errors", []) or [])
        summary = payload.get("summary", {}) or {}

        # Record the first validate hit (the one that matters for first-pass).
        if self._validated_count == 1:
            self._first_errors = errors
            self._first_summary = summary if isinstance(summary, dict) else None
            self.result.first_validate_errors = len(errors)

        self.result.cross_ref_errors_seen.extend(errors)
        if isinstance(summary, dict):
            self.result.rollback_rounds = max(
                self.result.rollback_rounds, int(summary.get("retry_count", 0))
            )

        self._approved = True
        return {"approved": True}

    # ---- node event hook ----
    def event_handler(self, node: str, update: dict[str, Any]) -> None:
        if node in ("__interrupt__", "__end__", "__start__"):
            return
        # Per-node timing: this callback fires AFTER the node finished, so
        # the elapsed since the previous node (or harness creation for the
        # first node) is this node's wall-clock duration.
        now = time.perf_counter()
        duration = round(now - self._last_node_t, 3)
        self.result.node_timings.append({"node": node, "duration_s": duration})
        self.result.phase_total_s[node] = round(
            self.result.phase_total_s.get(node, 0.0) + duration, 3
        )
        self._last_node_t = now

        self.result.node_sequence.append(node)
        # Per-node execution count (e.g. construction executed twice => rollback).
        self.result.node_counts[node] = self.result.node_counts.get(node, 0) + 1
        # A re-entry into intake/revise means the agent started over from the
        # top — count it as a rebuild.
        if node in ("intake", "revise"):
            self.result.rebuild_count += 1
        # Capture the simulate node's summary message (has idf path / status).
        if node == "simulate":
            self.result.reached_simulate = True
            msgs = update.get("messages") or []
            for m in msgs:
                content = getattr(m, "content", None) or str(m)
                if content:
                    self.result.simulate_message = str(content)
                    break

    # ---- final verdict computation ----
    def finalize(self, final_state: dict[str, Any]) -> None:
        # Pure modeling-quality signal: clean on the FIRST validate hit + no
        # automatic rollback happened at all.
        first_clean = not self._first_errors
        no_rollback = self.result.rollback_rounds == 0
        self.result.model_clean_first = first_clean and no_rollback

        # Did simulation actually succeed? Three independent signals:
        #  1) the simulate node message mentions a real idf path,
        #  2) EnergyPlus produced a result artifact under output_dir,
        #  3) eplusout.err has NO Error-level lines (Fatal/Severe).
        #    Warnings are tolerated.
        msg = (self.result.simulate_message or "")
        has_idf_in_msg = "idf=" in msg.lower() and "error" not in msg.lower()
        produced_output, out_files, err_path = _check_simulation_output(self.output_dir)
        self.result.output_files = out_files
        err_info = _parse_eplusout_err(err_path)
        self.result.err_fatal_count = err_info["fatal"]
        self.result.err_severe_count = err_info["severe"]
        self.result.err_warning_count = err_info["warning"]
        self.result.err_has_error_level = err_info["has_error_level"]

        # Extract the idf path the simulate node reported (best-effort).
        if "idf=" in msg:
            token = msg.split("idf=", 1)[1].strip().split()[0]
            self.result.idf_path = token or None

        self.result.simulation_ok = (
            produced_output
            and has_idf_in_msg
            and (not self.result.err_has_error_level)
        )

        # END-TO-END first-pass success: clean first model + no rollback +
        # simulation actually ran without Error-level diagnostics.
        self.result.first_pass = (
            self.result.model_clean_first and self.result.simulation_ok
        )
        # recovered = needed rollback/rebuild (not a clean first pass) but
        # still produced a runnable IDF in the end.
        self.result.recovered = (
            (not self.result.first_pass) and self.result.simulation_ok
        )

        if self._first_summary is not None:
            self.result.validate_summary = self._first_summary

    # ---- trace snapshot ----
    def snapshot_traces(self) -> None:
        try:
            traces = export_traces()
        except Exception as e:  # pragma: no cover - tracing is best-effort
            logger.warning("trace export failed for case {}: {}", self.case["id"], e)
            return
        self.result.phase_traces = traces
        # Aggregate per-phase tool-call stats: total calls, succeeded, failed.
        stats: dict[str, dict[str, int]] = {}
        for phase, entries in traces.items():
            calls = len(entries)
            ok = sum(1 for e in entries if e.get("success"))
            stats[phase] = {"calls": calls, "succeeded": ok, "failed": calls - ok}
        self.result.phase_tool_stats = stats


def _check_simulation_output(output_dir: Path) -> tuple[bool, list[str], Path | None]:
    """Return (ok, output_files, err_path) for a simulation output dir.

    ``ok`` is True if EnergyPlus wrote at least one canonical result
    artifact (eplusout.end / .sql / eplustbl.csv) — i.e. it actually ran
    to completion. The list of artifacts and the path to eplusout.err
    (if present) are returned so the caller can do error-level parsing.
    """
    if not output_dir.exists():
        return False, [], None
    artifacts: list[str] = []
    err_path: Path | None = None
    for p in output_dir.glob("**/*"):
        if not p.is_file():
            continue
        name = p.name.lower()
        if name in ("eplusout.end", "eplusout.sql", "eplustbl.csv"):
            artifacts.append(str(p))
        if name == "eplusout.err":
            err_path = p
    return bool(artifacts), artifacts, err_path


def _parse_eplusout_err(err_path: Path | None) -> dict[str, Any]:
    """Count severity lines in eplusout.err.

    EnergyPlus writes one line per diagnostic, tagged like
    ``** Fatal **``, ``** Severe **``, ``** Warning **``. We treat
    Fatal and Severe as "Error level" (must not be present for the run
    to count as clean); Warning is informational and ignored.

    Returns a dict with counts + a boolean ``has_error_level``.
    """
    counts = {"fatal": 0, "severe": 0, "warning": 0, "has_error_level": False}
    if err_path is None or not err_path.exists():
        return counts
    try:
        text = err_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return counts
    for line in text.splitlines():
        low = line.lower()
        # EnergyPlus severity tags look like "   ** Fatal **  ..."
        if "** fatal **" in low:
            counts["fatal"] += 1
        elif "** severe **" in low:
            counts["severe"] += 1
        elif "** warning **" in low:
            counts["warning"] += 1
    counts["has_error_level"] = (counts["fatal"] + counts["severe"]) > 0
    return counts


# ---------------------------------------------------------------------------
# Per-case runner
# ---------------------------------------------------------------------------
def _render_case_top_view(harness: "CaseHarness", out_base: Path) -> None:
    """Render a bird's-eye PNG for the case's produced IDF, if any.

    Best-effort: a render failure only logs a warning and never affects the
    test verdict. The IDF path comes from ``harness.result.idf_path`` (parsed
    from the simulate message); if that is missing or stale we fall back to
    globbing ``*.idf`` under the simulation output dir.
    """
    idf_path_str = harness.result.idf_path
    idf_path: Path | None = None
    if idf_path_str and Path(idf_path_str).exists():
        idf_path = Path(idf_path_str)
    else:
        # Fallback: the simulate node writes temp_<ts>.idf into sim_out.
        hits = sorted(Path(harness.output_dir).glob("**/*.idf"))
        if hits:
            idf_path = hits[-1]
    if idf_path is None:
        logger.info("[{}] no IDF found; skipping top-view render", harness.case["id"])
        return
    try:
        from agent_test.render_top_view import render_top_view

        out_png = out_base / "top_view.png"
        render_top_view(idf_path, out_png)
        logger.info("[{}] top-view rendered -> {}", harness.case["id"], out_png)
    except Exception as e:  # rendering is best-effort
        logger.warning("[{}] top-view render failed: {}", harness.case["id"], e)


def run_one_case(
    case: dict[str, Any],
    epw: Path,
    results_root: Path,
    timestamp: str,
    repeat_index: int = 0,
    use_images: bool = False,
    data_root: Path | None = None,
) -> CaseResult:
    case_id = case["id"]
    # Mirror the data tree into the results tree: results/<ts>/<rel>/rep_<i>.
    # rel is the case dir relative to data_root (e.g. residential/large/case_03).
    if data_root is not None:
        try:
            rel = Path(case["_dir"]).resolve().relative_to(data_root.resolve())
        except ValueError:
            rel = Path(case_id)
    else:
        rel = Path(case_id)
    out_base = results_root / timestamp / rel / f"rep_{repeat_index}"
    harness = CaseHarness(case, out_base / "sim_out", repeat_index=repeat_index)

    # Per-case log file so each run is fully auditable.
    log_path = out_base / "run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handler_id = logger.add(
        log_path, level="DEBUG", encoding="utf-8", mode="w", enqueue=True
    )

    logger.info(
        "===== CASE {} (rep {}) start =====", case_id, repeat_index
    )
    t0 = time.perf_counter()
    try:
        # Build a fresh graph per case so the InMemorySaver checkpointer
        # does not leak state between cases / repetitions.
        graph = build_graph()
        reset_traces()

        initial = AgentState(
            user_input=build_user_prompt(case),
            image_paths=(collect_images(case) if use_images else []),
        )
        context = SimContext(
            epw_path=epw,
            output_dir=Path(harness.output_dir),
        )
        config: RunnableConfig = {
            "configurable": {"thread_id": f"robust_{timestamp}_{case_id}_{repeat_index}"}
        }

        final_state = run_session(
            graph,
            initial,
            context,
            config,
            on_interrupt=harness.interrupt_handler,
            on_event=harness.event_handler,
        )
        harness.snapshot_traces()
        harness.finalize(dict(final_state))
        _render_case_top_view(harness, out_base)
    except Exception as e:
        harness.result.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        logger.exception("CASE {} crashed", case_id)
    finally:
        harness.result.elapsed_s = round(time.perf_counter() - t0, 2)
        logger.info(
            "===== CASE {} done: first_pass={} sim_ok={} rounds={} ({}s) =====",
            case_id,
            harness.result.first_pass,
            harness.result.simulation_ok,
            harness.result.rollback_rounds,
            harness.result.elapsed_s,
        )
        try:
            logger.remove(log_handler_id)
        except ValueError:
            pass

    return harness.result


# ---------------------------------------------------------------------------
# Aggregate reporting
# ---------------------------------------------------------------------------
def write_reports(
    results: list[CaseResult],
    timestamp: str,
    results_root: Path,
    epw: Path,
    temperature: float | None = None,
    repeat: int = 1,
) -> None:
    out_dir = results_root / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    # Full per-case (per-repetition) JSON
    (out_dir / "results.json").write_text(
        json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Aggregate summary
    n = len(results) or 1
    summary = {
        "timestamp": timestamp,
        "epw": str(epw),
        "temperature": temperature,
        "repeat": repeat,
        "total_runs": len(results),
        # first_pass = END-TO-END definition (clean first model + no rollback
        # + simulation ran with no Error-level err lines).
        "first_pass_ok": sum(r.first_pass for r in results),
        "first_pass_rate": round(sum(r.first_pass for r in results) / n, 4),
        # model_clean_first = pure modeling signal (clean first validate +
        # no rollback), regardless of whether EnergyPlus accepted it.
        "model_clean_first_ok": sum(r.model_clean_first for r in results),
        "model_clean_first_rate": round(
            sum(r.model_clean_first for r in results) / n, 4
        ),
        "recovered_ok": sum(r.recovered for r in results),
        "simulation_ok": sum(r.simulation_ok for r in results),
        "reached_simulate": sum(r.reached_simulate for r in results),
        "failed": sum(
            (not r.first_pass) and (not r.recovered) for r in results
        ),
        "crashed": sum(r.error is not None for r in results),
        "err_with_error_level": sum(r.err_has_error_level for r in results),
        "avg_rollback_rounds": round(
            sum(r.rollback_rounds for r in results) / n, 2
        ),
        "avg_rebuild_count": round(sum(r.rebuild_count for r in results) / n, 2),
        "avg_validate_hits": round(sum(r.validate_hits for r in results) / n, 2),
        "avg_first_validate_errors": round(
            sum(r.first_validate_errors for r in results) / n, 2
        ),
        "avg_elapsed_s": round(sum(r.elapsed_s for r in results) / n, 2),
        "total_err_fatal": sum(r.err_fatal_count for r in results),
        "total_err_severe": sum(r.err_severe_count for r in results),
        "total_err_warning": sum(r.err_warning_count for r in results),
    }

    # Average per-phase wall-clock across all runs (find the slow phase).
    phase_accum: dict[str, float] = {}
    for r in results:
        for phase, secs in r.phase_total_s.items():
            phase_accum[phase] = phase_accum.get(phase, 0.0) + secs
    summary["avg_phase_s"] = {
        phase: round(total / n, 2) for phase, total in sorted(
            phase_accum.items(), key=lambda kv: kv[1], reverse=True
        )
    }

    # Per-case stability across repetitions (when repeat > 1): for each case
    # id, how many of its repetitions were first-pass. A case that is
    # first-pass every time is "stable"; flaky cases flip-flop and are the
    # interesting robustness signal.
    per_case: dict[str, list[bool]] = {}
    for r in results:
        per_case.setdefault(r.case_id, []).append(r.first_pass)
    summary["per_case_stability"] = {
        cid: {
            "first_pass_count": sum(v),
            "repetitions": len(v),
            "first_pass_rate": round(sum(v) / len(v), 4) if v else 0.0,
        }
        for cid, v in sorted(per_case.items())
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Human-readable markdown report
    lines = [
        f"# Agent Robustness Benchmark — {timestamp}",
        "",
        f"- EPW: `{epw}`  |  Temperature: `{temperature}`  "
        f"|  Repetitions/case: **{repeat}**  |  Total runs: **{summary['total_runs']}**",
        "",
        "## Aggregate",
        "",
        f"- **一次成功 (first_pass, end-to-end): {summary['first_pass_ok']}"
        f" → {summary['first_pass_rate']*100:.1f}%**",
        f"  _(首次建模零交叉错误 + 零回滚 + 模拟跑通且 err 无 Error 级)_",
        f"- 建模一次干净 (model_clean_first, 纯建模口径): "
        f"{summary['model_clean_first_ok']} → "
        f"{summary['model_clean_first_rate']*100:.1f}%",
        f"- 跑通模拟 (simulation_ok): {summary['simulation_ok']}  "
        f"(其中 recovered 回滚后跑通: {summary['recovered_ok']})",
        f"- 失败 (failed): {summary['failed']}  |  崩溃 (crashed): "
        f"{summary['crashed']}  |  err 含 Error 级: "
        f"{summary['err_with_error_level']}",
        f"- 平均: 回滚 {summary['avg_rollback_rounds']} 轮  |  "
        f"重建 {summary['avg_rebuild_count']} 次  |  "
        f"validate 命中 {summary['avg_validate_hits']} 次  |  "
        f"首次错误 {summary['avg_first_validate_errors']} 条  |  "
        f"耗时 {summary['avg_elapsed_s']} s",
        f"- err 统计: Fatal {summary['total_err_fatal']}  |  "
        f"Severe {summary['total_err_severe']}  |  "
        f"Warning {summary['total_err_warning']}",
        f"- 各阶段平均耗时(s): "
        + "  ".join(
            f"{p} {s}" for p, s in summary["avg_phase_s"].items()
        ),
        "",
        "## Per-run detail",
        "",
        "| Case | rep | first_pass | model_clean | recovered | sim_ok | rollback | rebuild | validate× | err@1st | F/S/W | time(s) | slowest phase |",
        "|------|-----|-----------|-------------|-----------|---------|----------|---------|-----------|---------|-------|---------|---------------|",
    ]
    for r in results:
        # slowest phase for this run (name + seconds)
        if r.phase_total_s:
            slowest_phase, slowest_s = max(
                r.phase_total_s.items(), key=lambda kv: kv[1]
            )
            slowest = f"{slowest_phase} {slowest_s}s"
        else:
            slowest = "-"
        lines.append(
            f"| {r.case_id} | {r.repeat_index} "
            f"| {'✅' if r.first_pass else '❌'} "
            f"| {'✅' if r.model_clean_first else '❌'} "
            f"| {'✅' if r.recovered else '-'} "
            f"| {'✅' if r.simulation_ok else '❌'} "
            f"| {r.rollback_rounds} | {r.rebuild_count} | {r.validate_hits} "
            f"| {r.first_validate_errors} "
            f"| {r.err_fatal_count}/{r.err_severe_count}/{r.err_warning_count} "
            f"| {r.elapsed_s} | {slowest} |"
        )
    if repeat > 1:
        lines += [
            "",
            "## Per-case stability (across repetitions)",
            "",
            "| Case | first_pass / reps | rate |",
            "|------|------------------|------|",
        ]
        for cid, info in summary["per_case_stability"].items():
            lines.append(
                f"| {cid} | {info['first_pass_count']} / {info['repetitions']} "
                f"| {info['first_pass_rate']*100:.0f}% |"
            )
    lines.append("")
    lines.append("> `errors@1st-validate` = cross-ref errors at the agent's first")
    lines.append("> validate hit (0 ⇒ clean first pass; matches `first_pass`).")
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")

    logger.info("reports written to {}", out_dir)
    print("\n" + "\n".join(lines[1:]))


# ---------------------------------------------------------------------------
# LLM temperature override (process-level llm.yaml patch)
# ---------------------------------------------------------------------------
LLM_YAML = REPO_ROOT / "src" / "configs" / "llm.yaml"


def set_llm_temperature(temperature: float) -> str | None:
    """Rewrite ``temperature:`` in src/configs/llm.yaml in place.

    The phase agents each call ``create_llm()`` with no arguments, and
    ``create_llm`` re-reads ``llm.yaml`` on every call — there is no shared
    LLM singleton we can inject into. So the only way to pin the sampling
    temperature for a whole benchmark run is to edit the YAML before the
    first agent runs.

    We deliberately do NOT read .env's ``DEFAULT_TEMPERATURE``: the
    benchmark's temperature is controlled solely by ``--temperature`` so
    runs are reproducible and explicit.

    Returns the original temperature value (as a string) so the caller can
    restore it afterward, even if the script crashes. Leaves the file
    untouched and returns None if the line is not found.
    """
    text = LLM_YAML.read_text(encoding="utf-8")
    m = re.search(r"^(\s*temperature:\s*)(\S+)\s*$", text, flags=re.MULTILINE)
    if not m:
        logger.warning(
            "no `temperature:` line found in {}; leaving it unchanged", LLM_YAML
        )
        return None
    original = m.group(2)
    new_text = text[: m.start()] + f"{m.group(1)}{temperature}" + text[m.end():]
    LLM_YAML.write_text(new_text, encoding="utf-8")
    logger.info("llm.yaml temperature: {} -> {}", original, temperature)
    return original


def restore_llm_temperature(original: str | None) -> None:
    """Inverse of :func:`set_llm_temperature`."""
    if original is None:
        return
    text = LLM_YAML.read_text(encoding="utf-8")
    m = re.search(r"^(\s*temperature:\s*)(\S+)\s*$", text, flags=re.MULTILINE)
    if not m:
        return
    new_text = text[: m.start()] + f"{m.group(1)}{original}" + text[m.end():]
    LLM_YAML.write_text(new_text, encoding="utf-8")
    logger.info("llm.yaml temperature restored to {}", original)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="EnergyPlus Agent first-pass-success robustness benchmark."
    )
    ap.add_argument(
        "--epw",
        type=Path,
        default=DEFAULT_EPW,
        help=f"EPW weather file (default: {DEFAULT_EPW})",
    )
    ap.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma-separated case ids to run, e.g. --only 0,2,11. "
        "Default: run all discovered cases.",
    )
    ap.add_argument(
        "--data-root",
        type=Path,
        default=TEST_DATA_ROOT,
        help="Directory holding <case>/testdata_prompt.json subfolders.",
    )
    ap.add_argument(
        "--images",
        action="store_true",
        default=False,
        help="Pass the building drawings (top/front/side) declared in each "
        "testdata_prompt.json to the agent as multimodal input. OFF by "
        "default: the current phase runs TEXT-ONLY (the prompt asks the "
        "agent to derive geometry from the stated counts/area). Turn this "
        "on only with a vision-capable LLM.",
    )
    ap.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Override the LLM sampling temperature for this benchmark run "
        "(written into src/configs/llm.yaml, restored on exit). Does NOT "
        "read DEFAULT_TEMPERATURE from .env. If omitted, the YAML value "
        "(currently 0.7) is used as-is.",
    )
    ap.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="How many times to run each case. Repeat > 1 yields per-case "
        "stability stats in the report (e.g. a case that passes 3/5 times).",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    if not args.epw.exists():
        logger.error("EPW not found: {}", args.epw)
        sys.exit(2)
    if not args.data_root.exists():
        logger.error("test data root not found: {}", args.data_root)
        sys.exit(2)
    if args.repeat < 1:
        logger.error("--repeat must be >= 1, got {}", args.repeat)
        sys.exit(2)

    all_cases = discover_cases(args.data_root)
    if args.only:
        # --only accepts comma-separated PREFIXES against the relative-path id,
        # e.g. --only residential  (all residential)
        #      --only office/large  (all large offices)
        #      --only retail/small/case_03  (one case)
        prefixes = tuple(s.strip() for s in args.only.split(",") if s.strip())
        cases = [c for c in all_cases if c["id"].startswith(prefixes)]
        if not cases:
            logger.error(
                "no cases matched --only prefixes {}; available ids: {}",
                prefixes,
                [c["id"] for c in all_cases][:10],
            )
            sys.exit(2)
    else:
        cases = all_cases

    if not cases:
        logger.error("no cases to run")
        sys.exit(2)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    total_runs = len(cases) * args.repeat
    logger.info(
        "running {} case(s) x {} rep(s) = {} run(s); epw={}; ts={}; temp={}; "
        "images={}",
        len(cases),
        args.repeat,
        total_runs,
        args.epw,
        timestamp,
        args.temperature,
        "ON" if args.images else "OFF (text-only)",
    )

    # Pin the LLM temperature for the whole benchmark, restore on exit.
    original_temp: str | None = None
    if args.temperature is not None:
        original_temp = set_llm_temperature(args.temperature)

    results: list[CaseResult] = []
    try:
        run_idx = 0
        for case in cases:
            for rep in range(args.repeat):
                run_idx += 1
                logger.info(
                    "[{}/{}] case id={} rep={}",
                    run_idx,
                    total_runs,
                    case["id"],
                    rep,
                )
                res = run_one_case(
                    case,
                    args.epw,
                    RESULTS_DIR,
                    timestamp,
                    repeat_index=rep,
                    use_images=args.images,
                    data_root=args.data_root,
                )
                results.append(res)
    finally:
        if args.temperature is not None:
            restore_llm_temperature(original_temp)

    write_reports(
        results,
        timestamp,
        RESULTS_DIR,
        args.epw,
        temperature=args.temperature,
        repeat=args.repeat,
    )


if __name__ == "__main__":
    main()
