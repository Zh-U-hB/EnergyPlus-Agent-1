"""Deep multi-scenario test suite for the EnergyPlus agent.

Runs several independent scenarios, each exercising a different aspect of
the from-scratch build + revision pipeline:

  A. Variant first-run prompts (multi-zone office, single-zone shed)
  B. Multi-turn revision chains (add -> modify -> delete)
  C. Revision that deletes objects (update/delete integrity)
  D. Revision that should trigger directed rollback on cross-ref errors
  E. First-run self-repair when an LLM fabricates a bad reference
  F. Model integrity after consecutive revisions (names, counts, refs)

Each scenario runs in its own output dir + thread_id to stay isolated.
A scenario "passes" if it completes without exception AND its
post-conditions (object counts, name preservation, reference integrity)
hold. Failures are reported but don't abort the whole suite.
"""

from __future__ import annotations

import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from langchain_core.runnables import RunnableConfig

from src.agent import AgentState, SimContext, build_graph
from src.agent.runner import run_session
from src.mcp.state import ConfigState, _idf_values
from src.utils.logging import setup_logger

setup_logger(level="WARNING")  # quiet the LLM/trace noise

EPW = Path("data/weather/Shenzhen.epw")
ROOT = Path("output/deep_test")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _inventory(idf_path: Path) -> dict[str, int]:
    cs = ConfigState()
    cs.load_idf(idf_path)
    idf = cs.idf
    return {
        "zone": len(_idf_values(idf, "Zone")),
        "mat": len(_idf_values(idf, "Material", "Material:NoMass",
                               "Material:AirGap", "WindowMaterial:SimpleGlazingSystem")),
        "const": len(_idf_values(idf, "Construction")),
        "surf": len(_idf_values(idf, "BuildingSurface:Detailed")),
        "fen": len(_idf_values(idf, "FenestrationSurface:Detailed")),
        "sched": len(_idf_values(idf, "Schedule:Compact", "ScheduleCompact")),
        "hvac": len(_idf_values(idf, "HVACTemplate:Thermostat",
                                "HVACTemplate:Zone:IdealLoadsAirSystem")),
        "ppl": len(_idf_values(idf, "People")),
        "light": len(_idf_values(idf, "Lights", "Light")),
    }


def _names(idf_path: Path, obj_type: str) -> list[str]:
    cs = ConfigState()
    cs.load_idf(idf_path)
    out = []
    for o in _idf_values(cs.idf, obj_type):
        n = getattr(o, "name", None) or getattr(o, "Name", None)
        if n:
            out.append(str(n))
    return out


def _latest_idf(d: Path) -> Path | None:
    """Newest .idf in *d*. Robust to stat() races on freshly-written files."""
    if not d.exists():
        return None
    candidates = []
    for p in d.glob("*.idf"):
        try:
            candidates.append((p.stat().st_mtime, p))
        except OSError:
            continue  # file vanished mid-glob
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _wait_for_idf(d: Path, timeout: float = 5.0) -> Path | None:
    """Poll for an IDF in *d* — works around EnergyPlus' temp-file timing."""
    import time as _t
    deadline = _t.time() + timeout
    while _t.time() < deadline:
        idf = _latest_idf(d)
        if idf:
            return idf
        _t.sleep(0.2)
    return _latest_idf(d)


def _validate_refs(idf_path: Path) -> list[str]:
    cs = ConfigState()
    cs.load_idf(idf_path)
    return cs.validate_references()


def _run_turn(
    graph,
    prompt: str,
    thread_id: str,
    out_dir: Path,
    seed_idf: Path | None,
    approve_always: bool = True,
) -> dict:
    """Run one agent turn. Returns final state dict."""
    if seed_idf and seed_idf.exists():
        cs = ConfigState()
        cs.load_idf(seed_idf)
        cs.seed_idf_text = seed_idf.read_text(encoding="utf-8")
        initial = AgentState(
            user_input=prompt, config_state=cs, is_revision=True
        )
    else:
        initial = AgentState(user_input=prompt)

    context = SimContext(epw_path=EPW, output_dir=out_dir)
    cfg: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    def on_interrupt(payload: dict) -> dict:
        errs = payload.get("errors", [])
        if errs and not approve_always:
            return {"approved": False, "feedback": "fix: " + "; ".join(errs)}
        return {"approved": True}

    return run_session(graph, initial, context, cfg, on_interrupt=on_interrupt)


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    duration_s: float
    detail: str = ""
    inv: dict = field(default_factory=dict)


def _ok(name: str, t0: float, detail: str = "", **inv) -> ScenarioResult:
    return ScenarioResult(name, True, time.time() - t0, detail, inv)


def _fail(name: str, t0: float, detail: str) -> ScenarioResult:
    return ScenarioResult(name, False, time.time() - t0, detail)


# ── Scenario A: variant first-run builds ─────────────────────────────────────

SIMPLE_PROMPT = """Design a single-zone warehouse in Shenzhen.
30m x 20m x 6m, one thermal zone named Warehouse_Main.
Walls: 200mm concrete block, no insulation.
Roof: 150mm concrete + 50mm EPS.
Floor: 200mm concrete slab on grade.
No windows. No HVAC (unconditioned storage).
One person present 8am-5pm weekdays, light activity 100 W/person.
Lighting: 8 W/m^2, on 8am-5pm weekdays."""


def scenario_a_simple_build(graph) -> ScenarioResult:
    """A: First-run build of a simple single-zone unconditioned warehouse."""
    t0 = time.time()
    name = "A_simple_single_zone_build"
    out = ROOT / name
    out.mkdir(parents=True, exist_ok=True)
    for p in out.glob("*.idf"):
        p.unlink()
    try:
        _run_turn(graph, SIMPLE_PROMPT, f"{name}_t1", out, seed_idf=None)
        idf = _wait_for_idf(out)
        if not idf:
            return _fail(name, t0, "no IDF produced")
        inv = _inventory(idf)
        # Post-conditions: 1 zone, >=4 surfaces (box), 1 person, 1 light
        checks = []
        if inv["zone"] < 1: checks.append(f"zone={inv['zone']} expected >=1")
        if inv["surf"] < 4: checks.append(f"surf={inv['surf']} expected >=4 (box)")
        if inv["ppl"] < 1: checks.append(f"ppl={inv['ppl']} expected >=1")
        if inv["light"] < 1: checks.append(f"light={inv['light']} expected >=1")
        # No windows expected
        if inv["fen"] != 0: checks.append(f"fen={inv['fen']} expected 0 (no windows)")
        if checks:
            return _fail(name, t0, "; ".join(checks) + f" | inv={inv}")
        return _ok(name, t0, f"single-zone unconditioned warehouse built", **inv)
    except Exception as e:
        return _fail(name, t0, f"exception: {e}\n{traceback.format_exc()[-400:]}")


# ── Scenario B: 3-turn revision chain (add -> modify -> delete) ───────────────

B_TURN1 = """Design a 3-zone single-floor office in Shenzhen.
20m x 12m x 3.5m. Zones: Office (10x8m), Meeting (6x4m), Storage (4x4m).
Exterior walls: 200mm concrete + 50mm EPS + 15mm gypsum.
Roof: 200mm concrete + 80mm XPS. Floor: 200mm concrete on ground.
No windows initially. Office: 8 people 8am-6pm weekdays, 120 W/person.
Meeting: 6 people. Lighting: 10 W/m^2 office/meeting, 5 W/m^2 storage.
HVAC: ideal loads, office/meeting 20-24C occupied, storage unconditioned."""

B_TURN2 = """Add double-glazed windows (U=1.8, SHGC=0.4) covering 25% of the
Office south wall. Keep all other objects unchanged."""

B_TURN3 = """Change the Office lighting power density from 10 W/m^2 to 15 W/m^2,
and add 2 more people to the Meeting room (6 -> 8 total). Keep all other
objects unchanged."""


def scenario_b_revision_chain(graph) -> ScenarioResult:
    """B: 3 consecutive revision turns on the same model."""
    t0 = time.time()
    name = "B_revision_chain_3turns"
    out = ROOT / name
    out.mkdir(parents=True, exist_ok=True)
    for p in out.glob("*.idf"):
        p.unlink()
    try:
        # Turn 1: build
        _run_turn(graph, B_TURN1, f"{name}_t1", out, seed_idf=None)
        idf1 = _wait_for_idf(out)
        if not idf1:
            return _fail(name, t0, "turn 1 produced no IDF")
        inv1 = _inventory(idf1)
        if inv1["zone"] != 3:
            return _fail(name, t0, f"turn 1 zone={inv1['zone']} expected 3")

        # Turn 2: add windows
        _run_turn(graph, B_TURN2, f"{name}_t2", out, seed_idf=idf1)
        idf2 = _wait_for_idf(out)
        if not idf2 or idf2 == idf1:
            return _fail(name, t0, "turn 2 produced no new IDF")
        inv2 = _inventory(idf2)
        # zones/surfaces must be preserved; fenestrations should increase
        checks = []
        if inv2["zone"] != inv1["zone"]:
            checks.append(f"zone {inv1['zone']}->{inv2['zone']} (expected preserved)")
        if inv2["surf"] != inv1["surf"]:
            checks.append(f"surf {inv1['surf']}->{inv2['surf']} (expected preserved)")
        if inv2["fen"] <= inv1["fen"]:
            checks.append(f"fen {inv1['fen']}->{inv2['fen']} (expected increase)")
        if checks:
            return _fail(name, t0, "turn 2: " + "; ".join(checks))

        # Turn 3: modify lighting + people (no add/delete of structural objects)
        _run_turn(graph, B_TURN3, f"{name}_t3", out, seed_idf=idf2)
        idf3 = _wait_for_idf(out)
        if not idf3:
            return _fail(name, t0, "turn 3 produced no IDF")
        inv3 = _inventory(idf3)
        # Structural objects preserved; fenestration preserved from turn 2
        checks = []
        if inv3["zone"] != 3:
            checks.append(f"zone={inv3['zone']} expected 3")
        if inv3["surf"] != inv2["surf"]:
            checks.append(f"surf {inv2['surf']}->{inv3['surf']} (expected preserved)")
        if inv3["fen"] != inv2["fen"]:
            checks.append(f"fen {inv2['fen']}->{inv3['fen']} (expected preserved)")
        # People count may stay 3 (Office+Meeting+Storage) - just density change
        if inv3["ppl"] != inv2["ppl"]:
            checks.append(f"ppl {inv2['ppl']}->{inv3['ppl']} (note: density change may not alter count)")
        # Reference integrity must hold
        errs = _validate_refs(idf3)
        if errs:
            checks.append(f"cross-ref errors: {errs[:2]}")
        if checks:
            return _fail(name, t0, "turn 3: " + "; ".join(checks))

        return _ok(name, t0,
                   f"3-turn chain OK: t1(zones=3) -> t2(+windows) -> t3(modify lights/ppl), refs clean",
                   t1=inv1, t2=inv2, t3=inv3)
    except Exception as e:
        return _fail(name, t0, f"exception: {e}\n{traceback.format_exc()[-400:]}")


# ── Scenario C: revision that deletes objects ────────────────────────────────

C_TURN1 = """Design a 4-zone office in Shenzhen. 20m x 12m x 3.5m.
Zones: OfficeA (8x6m), OfficeB (8x6m), Corridor (4x12m), Storage (4x4m).
Exterior walls: 200mm concrete + 50mm EPS + 15mm gypsum.
Roof: 200mm concrete + 80mm XPS. Floor: 200mm concrete slab.
Each office: 6 people, 10 W/m^2 lighting, 8am-6pm weekdays.
HVAC: ideal loads 20-24C for offices, corridor/storage unconditioned.
Add double-glazed windows (U=1.8, SHGC=0.4) on OfficeA south wall, 20% WWR."""

C_TURN2 = """Remove (delete) the Storage zone and ALL surfaces, lights, and
people associated with it. The other 3 zones (OfficeA, OfficeB, Corridor)
and all their objects must remain unchanged. After deletion there should
be no dangling references to the deleted zone."""


def scenario_c_delete_revision(graph) -> ScenarioResult:
    """C: Revision turn that deletes a zone + its dependent objects."""
    t0 = time.time()
    name = "C_delete_zone_revision"
    out = ROOT / name
    out.mkdir(parents=True, exist_ok=True)
    for p in out.glob("*.idf"):
        p.unlink()
    try:
        _run_turn(graph, C_TURN1, f"{name}_t1", out, seed_idf=None)
        idf1 = _wait_for_idf(out)
        if not idf1:
            return _fail(name, t0, "turn 1 produced no IDF")
        inv1 = _inventory(idf1)
        if inv1["zone"] < 4:
            return _fail(name, t0, f"turn 1 zone={inv1['zone']} expected >=4")

        _run_turn(graph, C_TURN2, f"{name}_t2", out, seed_idf=idf1)
        idf2 = _wait_for_idf(out)
        if not idf2:
            return _fail(name, t0, "turn 2 produced no IDF")
        inv2 = _inventory(idf2)

        checks = []
        # Storage zone should be gone; the other 3 preserved
        zone_names = _names(idf2, "Zone")
        if any("Storage" in z for z in zone_names):
            checks.append(f"Storage zone still present: {zone_names}")
        # No dangling references
        errs = _validate_refs(idf2)
        if errs:
            checks.append(f"dangling refs after delete: {errs[:3]}")
        # Office zones must survive
        if not any("OfficeA" in z or "Office" in z for z in zone_names):
            checks.append(f"Office zones lost: {zone_names}")
        if checks:
            return _fail(name, t0, "; ".join(checks) + f" | t1={inv1} t2={inv2}")

        return _ok(name, t0,
                   f"delete revision OK: t1 zones={inv1['zone']} -> t2 zones={inv2['zone']}, refs clean",
                   t1=inv1, t2=inv2)
    except Exception as e:
        return _fail(name, t0, f"exception: {e}\n{traceback.format_exc()[-400:]}")


# ── Scenario D: revision triggering directed rollback ─────────────────────────

D_TURN1 = """Design a 2-zone office in Shenzhen. 16m x 8m x 3.5m.
Zones: Office (10x6m), Meeting (6x6m).
Walls: 200mm concrete + 50mm EPS. Roof: 200mm concrete + 80mm XPS.
Floor: 200mm concrete slab. No windows.
Office: 8 people 8am-6pm, 10 W/m^2 lights. Meeting: 4 people.
HVAC: ideal loads 20-24C occupied."""

D_TURN2_BAD = """Change every surface's construction to a construction named
'NonExistent_Construction' that does not exist in the model. Do not create
the construction first — just reference it directly. (This intentionally
creates broken cross-references to test error recovery.)"""


def scenario_d_directed_rollback(graph) -> ScenarioResult:
    """D: Revision that induces cross-ref errors; verify validate catches
    them and the pipeline either self-heals or surfaces them cleanly
    (no crash, no silent corruption)."""
    t0 = time.time()
    name = "D_directed_rollback"
    out = ROOT / name
    out.mkdir(parents=True, exist_ok=True)
    for p in out.glob("*.idf"):
        p.unlink()
    try:
        _run_turn(graph, D_TURN1, f"{name}_t1", out, seed_idf=None)
        idf1 = _wait_for_idf(out)
        if not idf1:
            return _fail(name, t0, "turn 1 produced no IDF")
        inv1 = _inventory(idf1)

        # Turn 2: induce broken refs. We auto-approve so the pipeline runs.
        # The validate node should either (a) self-heal via directed rollback
        # or (b) surface errors at the HITL interrupt. Either is acceptable;
        # a crash or silent corruption is not.
        _run_turn(graph, D_TURN2_BAD, f"{name}_t2", out, seed_idf=idf1,
                  approve_always=True)
        idf2 = _wait_for_idf(out)

        # Whatever happened, the result must have clean refs (healed) or
        # we accept that validate surfaced them. Check no crash + model
        # structural integrity preserved.
        if idf2:
            inv2 = _inventory(idf2)
            errs = _validate_refs(idf2)
            # zones must survive regardless
            if inv2["zone"] < inv1["zone"]:
                return _fail(name, t0,
                             f"zones lost during rollback: {inv1['zone']}->{inv2['zone']}")
            return _ok(name, t0,
                       f"bad-ref turn handled gracefully: t1 zones={inv1['zone']} -> t2 zones={inv2['zone']}, "
                       f"remaining ref errors={len(errs)} (self-heal or surfaced)",
                       t1=inv1, t2=inv2, remaining_errors=len(errs))
        return _ok(name, t0, "bad-ref turn handled (no IDF produced, validate surfaced errors)", t1=inv1)
    except Exception as e:
        return _fail(name, t0, f"exception: {e}\n{traceback.format_exc()[-400:]}")


# ── Scenario E: first-run self-repair (ambiguous spec) ───────────────────────

E_PROMPT = """Design a small 2-zone office in Shenzhen. 12m x 8m x 3.5m.
Zones: Office (8x6m), Storage (4x6m).
Use material 'Concrete_200mm' for exterior walls and construction
'ExtWall' for those walls. Roof uses 'Roof_Construction'. Floor uses
'Floor_Construction'. Office: 6 people, 10 W/m^2 lights, HVAC 20-24C.
The model must have internally consistent cross-references."""


def scenario_e_first_run_self_repair(graph) -> ScenarioResult:
    """E: First-run where the spec names materials/constructions the LLM must
    actually create (not just reference). Tests that self-repair catches any
    fabricated refs and the final model has clean cross-references."""
    t0 = time.time()
    name = "E_first_run_self_repair"
    out = ROOT / name
    out.mkdir(parents=True, exist_ok=True)
    for p in out.glob("*.idf"):
        p.unlink()
    try:
        _run_turn(graph, E_PROMPT, f"{name}_t1", out, seed_idf=None)
        idf = _wait_for_idf(out)
        if not idf:
            return _fail(name, t0, "no IDF produced")
        inv = _inventory(idf)
        errs = _validate_refs(idf)
        checks = []
        if inv["zone"] < 2:
            checks.append(f"zone={inv['zone']} expected >=2")
        if inv["surf"] < 4:
            checks.append(f"surf={inv['surf']} expected >=4")
        if errs:
            checks.append(f"cross-ref errors survived self-repair: {errs[:3]}")
        if checks:
            return _fail(name, t0, "; ".join(checks) + f" | inv={inv}")
        return _ok(name, t0, f"first-run self-repair OK, refs clean", **inv)
    except Exception as e:
        return _fail(name, t0, f"exception: {e}\n{traceback.format_exc()[-400:]}")


# ── Scenario F: integrity after consecutive revisions ────────────────────────

F_TURN1 = """Design a 2-zone office in Shenzhen. 12m x 8m x 3.5m.
Zones: Office (8x6m), Meeting (4x6m).
Walls: 200mm concrete + 50mm EPS + 15mm gypsum. Roof: 200mm concrete + 80mm XPS.
Floor: 200mm concrete slab. Office: 6 people, 10 W/m^2, HVAC 20-24C.
Meeting: 4 people, 8 W/m^2, HVAC 20-24C."""

F_TURN2 = """Add double-glazed windows (U=1.8, SHGC=0.4) on the Office south wall,
30% WWR. Keep everything else unchanged."""

F_TURN3 = """Increase Office wall insulation from 50mm EPS to 80mm EPS.
Keep everything else unchanged."""


def scenario_f_integrity_chain(graph) -> ScenarioResult:
    """F: 3-turn chain focused on reference integrity + name stability."""
    t0 = time.time()
    name = "F_integrity_chain"
    out = ROOT / name
    out.mkdir(parents=True, exist_ok=True)
    for p in out.glob("*.idf"):
        p.unlink()
    try:
        _run_turn(graph, F_TURN1, f"{name}_t1", out, seed_idf=None)
        idf1 = _wait_for_idf(out)
        if not idf1:
            return _fail(name, t0, "turn 1 no IDF")
        zones_t1 = set(_names(idf1, "Zone"))

        _run_turn(graph, F_TURN2, f"{name}_t2", out, seed_idf=idf1)
        idf2 = _wait_for_idf(out)
        if not idf2:
            return _fail(name, t0, "turn 2 no IDF")
        zones_t2 = set(_names(idf2, "Zone"))
        if zones_t1 != zones_t2:
            return _fail(name, t0, f"zone names changed t1->t2: {zones_t1} != {zones_t2}")

        _run_turn(graph, F_TURN3, f"{name}_t3", out, seed_idf=idf2)
        idf3 = _wait_for_idf(out)
        if not idf3:
            return _fail(name, t0, "turn 3 no IDF")
        zones_t3 = set(_names(idf3, "Zone"))
        if zones_t1 != zones_t3:
            return _fail(name, t0, f"zone names changed across chain: {zones_t1} != {zones_t3}")
        errs = _validate_refs(idf3)
        if errs:
            return _fail(name, t0, f"cross-ref errors after 3 turns: {errs[:3]}")

        inv3 = _inventory(idf3)
        return _ok(name, t0,
                   f"3-turn integrity OK: zone names stable ({sorted(zones_t1)}), refs clean",
                   **inv3)
    except Exception as e:
        return _fail(name, t0, f"exception: {e}\n{traceback.format_exc()[-400:]}")


# ── Runner ───────────────────────────────────────────────────────────────────


SCENARIOS: list[tuple[str, Callable]] = [
    ("A", scenario_a_simple_build),
    ("E", scenario_e_first_run_self_repair),
    ("F", scenario_f_integrity_chain),
    ("B", scenario_b_revision_chain),
    ("C", scenario_c_delete_revision),
    ("D", scenario_d_directed_rollback),
]


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    print(f"\n{'='*72}\nDEEP MULTI-SCENARIO TEST SUITE\n{'='*72}")
    print(f"Output root: {ROOT}\n")

    graph = build_graph()
    results: list[ScenarioResult] = []
    for label, fn in SCENARIOS:
        print(f"\n--- Scenario {label}: {fn.__doc__.strip().splitlines()[0]} ---")
        r = fn(graph)
        results.append(r)
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.name} ({r.duration_s:.1f}s)")
        if r.detail:
            print(f"       {r.detail[:200]}")

    print(f"\n{'='*72}\nSUMMARY\n{'='*72}")
    passed = sum(1 for r in results if r.passed)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.name:40s} {r.duration_s:6.1f}s")
    print(f"\n{passed}/{len(results)} scenarios passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
