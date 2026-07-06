#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate Figure 2 (multi-stage Agent orchestration workflow).

The figure is a reader-facing orchestration map, not a raw LangGraph edge dump.
Only the normal execution path is drawn with arrows. Error handling, state
merging, RAG, and human/design feedback are summarized as routing rules in a
separate control band so the paper figure remains legible.

Run:
    python paper/scripts/fig2_agent_workflow.py
Output:
    paper/figures/fig2_agent_workflow.png
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon


def _font() -> FontProperties:
    candidates = [
        os.environ.get("NOTO_CJK_PATH", ""),
        r"C:/Windows/Fonts/msyh.ttc",
        r"C:/Windows/Fonts/simhei.ttf",
        r"C:/Windows/Fonts/simsun.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for item in candidates:
        if item and Path(item).exists():
            return FontProperties(fname=item)
    return FontProperties()


FONT = _font()


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def top(self) -> float:
        return self.y + self.h

    @property
    def bottom(self) -> float:
        return self.y


W, H = 18.0, 10.2

BG = "#FFFFFF"
INK = "#121417"
MUTED = "#4B5563"
LIGHT_TEXT = "#697386"
GRID = "#D5DCE6"

BLUE = "#315F9F"
BLUE_FILL = "#F2F6FF"
GREEN = "#4E7D57"
GREEN_FILL = "#F0F8F1"
AMBER = "#A06D2C"
AMBER_FILL = "#FFF7E8"
PURPLE = "#7660A8"
PURPLE_FILL = "#F6F1FF"
RED = "#C64B40"
RED_FILL = "#FFF4F2"
GRAY_FILL = "#F8FAFC"


def label(
    ax,
    x: float,
    y: float,
    text: str,
    *,
    size: float = 8.0,
    weight: str = "normal",
    color: str = INK,
    ha: str = "center",
    va: str = "center",
    style: str = "normal",
    z: int = 8,
) -> None:
    ax.text(
        x,
        y,
        text,
        ha=ha,
        va=va,
        fontsize=size,
        fontproperties=FONT,
        fontweight=weight,
        fontstyle=style,
        color=color,
        zorder=z,
        linespacing=1.18,
    )


def box(
    ax,
    rect: Rect,
    *,
    fc: str = "white",
    ec: str = BLUE,
    lw: float = 1.0,
    radius: float = 0.08,
    z: int = 3,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (rect.x, rect.y),
            rect.w,
            rect.h,
            boxstyle=f"round,pad=0.018,rounding_size={radius}",
            facecolor=fc,
            edgecolor=ec,
            linewidth=lw,
            zorder=z,
        )
    )


def arrow(
    ax,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    color: str = INK,
    lw: float = 1.25,
    ms: float = 11.0,
    z: int = 7,
) -> None:
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=ms,
            linewidth=lw,
            color=color,
            connectionstyle="arc3,rad=0",
            zorder=z,
        )
    )


def stage(ax, rect: Rect, number: str, title: str, subtitle: str, *, fc: str, ec: str) -> None:
    box(ax, rect, fc=fc, ec=ec, lw=1.15, radius=0.10, z=2)
    label(ax, rect.x + 0.20, rect.top - 0.24, f"{number}. {title}", size=9.1, weight="bold", ha="left")
    label(ax, rect.x + 0.20, rect.top - 0.54, subtitle, size=5.9, color=MUTED, ha="left")


def node(
    ax,
    rect: Rect,
    title: str,
    subtitle: str = "",
    *,
    fc: str = "white",
    ec: str = BLUE,
    title_size: float = 7.0,
    sub_size: float = 5.1,
    rag: bool = False,
) -> None:
    box(ax, rect, fc=fc, ec=ec, lw=0.9, radius=0.055, z=5)
    if rag:
        tag = Rect(rect.right - 0.39, rect.top - 0.19, 0.30, 0.13)
        box(ax, tag, fc=GREEN_FILL, ec=GREEN, lw=0.45, radius=0.025, z=7)
        label(ax, tag.cx, tag.cy, "RAG", size=3.8, weight="bold", color=GREEN, z=9)
    label(ax, rect.cx, rect.cy + (0.09 if subtitle else 0.0), title, size=title_size, weight="bold")
    if subtitle:
        label(ax, rect.cx, rect.cy - 0.17, subtitle, size=sub_size, color=MUTED)


def diamond(ax, rect: Rect, title: str, subtitle: str, *, fc: str, ec: str) -> None:
    points = [
        (rect.cx, rect.top),
        (rect.right, rect.cy),
        (rect.cx, rect.bottom),
        (rect.left, rect.cy),
    ]
    ax.add_patch(Polygon(points, closed=True, facecolor=fc, edgecolor=ec, linewidth=1.05, zorder=5))
    label(ax, rect.cx, rect.cy + 0.08, title, size=7.2, weight="bold")
    label(ax, rect.cx, rect.cy - 0.18, subtitle, size=5.1, color=MUTED)


def pill(ax, rect: Rect, text: str, *, fc: str, ec: str, color: str) -> None:
    box(ax, rect, fc=fc, ec=ec, lw=0.75, radius=0.08, z=5)
    label(ax, rect.cx, rect.cy, text, size=5.5, weight="bold", color=color)


def note(ax, x: float, y: float, text: str, *, color: str = MUTED, size: float = 5.35) -> None:
    label(ax, x, y, text, size=size, ha="left", va="top", color=color)


def section_rule(ax, y: float, text: str) -> None:
    label(ax, 0.55, y + 0.20, text, size=9.2, weight="bold", ha="left")
    ax.plot([0.55, W - 0.55], [y, y], color=GRID, lw=0.9, zorder=1)


def parallel_label(ax, rect: Rect, text: str, *, color: str = BLUE) -> None:
    label(ax, rect.right - 0.32, rect.top - 0.24, text, size=5.4, weight="bold", color=color)


def main() -> None:
    fig, ax = plt.subplots(figsize=(18, 9.4), dpi=180)
    fig.patch.set_facecolor(BG)
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")

    section_rule(ax, 9.25, "Normal execution path")

    y, h = 4.55, 3.90
    entry = Rect(0.55, y, 2.05, h)
    foundation = Rect(2.88, y, 2.55, h)
    main_y = y + 1.05
    gate_a = Rect(5.78, main_y - 0.575, 1.05, 1.15)
    envelope = Rect(7.18, y, 2.55, h)
    loads = Rect(10.03, y, 2.40, h)
    validate = Rect(12.78, y, 2.10, h)
    simulation = Rect(15.20, y, 2.25, h)

    stage(ax, entry, "1", "Entry", "first run or revision", fc=BLUE_FILL, ec=BLUE)
    stage(ax, foundation, "2", "Foundation", "parallel fan-out", fc=BLUE_FILL, ec=BLUE)
    stage(ax, envelope, "3", "Envelope", "sequential dependencies", fc=AMBER_FILL, ec=AMBER)
    stage(ax, loads, "4", "Loads & systems", "parallel fan-out", fc=BLUE_FILL, ec=BLUE)
    stage(ax, validate, "5", "Validate + review", "gates before simulation", fc=PURPLE_FILL, ec=PURPLE)
    stage(ax, simulation, "6", "Simulate + analyze", "EnergyPlus outputs", fc=GRAY_FILL, ec=BLUE)

    # Entry stage.
    label(ax, entry.cx, entry.y + 2.86, "START router selects one", size=5.7, color=MUTED)
    n_intake = Rect(entry.x + 0.22, entry.y + 2.18, 0.78, 0.43)
    n_revise = Rect(entry.x + 1.08, entry.y + 2.18, 0.78, 0.43)
    n_state = Rect(entry.x + 0.30, entry.y + 1.02, 1.45, 0.52)
    node(ax, n_intake, "intake", "first", ec=BLUE, title_size=6.1, sub_size=4.5)
    node(ax, n_revise, "revise", "iter.", ec=BLUE, title_size=6.1, sub_size=4.5)
    node(ax, n_state, "AgentState", "intent + seed IDF", ec=AMBER, fc=AMBER_FILL, title_size=6.8)
    merge_x = entry.cx
    ax.plot([n_intake.cx, n_intake.cx, merge_x], [n_intake.bottom, entry.y + 1.88, entry.y + 1.88], color=BLUE, lw=0.85, zorder=6)
    ax.plot([n_revise.cx, n_revise.cx, merge_x], [n_revise.bottom, entry.y + 1.88, entry.y + 1.88], color=BLUE, lw=0.85, zorder=6)
    arrow(ax, (merge_x, entry.y + 1.88), (n_state.cx, n_state.top), color=BLUE, lw=0.85, ms=8)
    note(ax, entry.x + 0.22, entry.y + 0.66, "IntakeOutput:\nbuilding + site\n9 subsystem specs\noptional image context", size=4.75)

    # Foundation stage: parallel branches are shown as a stack, not as several wires.
    f_nodes = [
        Rect(foundation.x + 0.32, foundation.y + 2.25, 1.38, 0.43),
        Rect(foundation.x + 0.32, foundation.y + 1.54, 1.38, 0.43),
        Rect(foundation.x + 0.32, foundation.y + 0.83, 1.38, 0.43),
    ]
    node(ax, f_nodes[0], "zone", "thermal zones", ec=BLUE, title_size=6.8)
    node(ax, f_nodes[1], "material", "properties", ec=GREEN, fc=GREEN_FILL, title_size=6.8, rag=True)
    node(ax, f_nodes[2], "schedule", "profiles", ec=GREEN, fc=GREEN_FILL, title_size=6.8, rag=True)
    parallel_label(ax, foundation, "merge")
    ax.plot([foundation.right - 0.45, foundation.right - 0.45], [f_nodes[-1].cy, f_nodes[0].cy], color=BLUE, lw=0.9, zorder=5)
    for rect in f_nodes:
        ax.plot([rect.right, foundation.right - 0.45], [rect.cy, rect.cy], color=BLUE, lw=0.9, zorder=5)
    note(ax, foundation.x + 0.26, foundation.y + 0.42, "Consumes: zone/material/schedule specs\nProduces: Zone, Material/WindowMaterial,\nScheduleTypeLimits + ScheduleCompact\nRule: exact cross-object names", size=4.65)

    diamond(ax, gate_a, "early\ncross-ref", "Gate A", fc=PURPLE_FILL, ec=PURPLE)
    label(ax, gate_a.cx, gate_a.bottom - 0.24, "fail -> Stage 5", size=5.2, color=RED)
    note(ax, gate_a.left - 0.15, gate_a.bottom - 0.50, "validate_references()\nearly identity check", size=4.5)

    # Envelope stage.
    n_con = Rect(envelope.x + 0.48, envelope.y + 2.30, 1.55, 0.43)
    n_surf = Rect(envelope.x + 0.48, envelope.y + 1.56, 1.55, 0.43)
    n_fen = Rect(envelope.x + 0.48, envelope.y + 0.82, 1.55, 0.43)
    node(ax, n_con, "construction", "layer stack", ec=GREEN, fc=GREEN_FILL, title_size=6.4, rag=True)
    node(ax, n_surf, "surface", "zone + construction", ec=AMBER, title_size=6.8)
    node(ax, n_fen, "fenestration", "surface refs", ec=AMBER, title_size=6.0)
    arrow(ax, (n_con.cx, n_con.bottom), (n_surf.cx, n_surf.top), color=AMBER, lw=0.9, ms=8)
    arrow(ax, (n_surf.cx, n_surf.bottom), (n_fen.cx, n_fen.top), color=AMBER, lw=0.9, ms=8)
    note(ax, envelope.x + 0.26, envelope.y + 0.42, "Dependency chain:\nconstruction <- materials\nsurface <- zones + constructions\nfenestration <- parent surface + window construction", size=4.75)

    # Loads/system stage.
    l_nodes = [
        Rect(loads.x + 0.32, loads.y + 2.25, 1.30, 0.43),
        Rect(loads.x + 0.32, loads.y + 1.54, 1.30, 0.43),
        Rect(loads.x + 0.32, loads.y + 0.83, 1.30, 0.43),
    ]
    node(ax, l_nodes[0], "hvac", "ideal loads", ec=GREEN, fc=GREEN_FILL, title_size=6.8, rag=True)
    node(ax, l_nodes[1], "people", "occupancy", ec=BLUE, title_size=6.8)
    node(ax, l_nodes[2], "lights", "lighting", ec=BLUE, title_size=6.8)
    parallel_label(ax, loads, "merge")
    ax.plot([loads.right - 0.40, loads.right - 0.40], [l_nodes[-1].cy, l_nodes[0].cy], color=BLUE, lw=0.9, zorder=5)
    for rect in l_nodes:
        ax.plot([rect.right, loads.right - 0.40], [rect.cy, rect.cy], color=BLUE, lw=0.9, zorder=5)
    note(ax, loads.x + 0.24, loads.y + 0.42, "Consumes: zones + schedules + envelope refs\nProduces: thermostats, ideal loads,\nPeople and Lights objects", size=4.75)

    # Validation/review stage.
    n_cref = Rect(validate.x + 0.33, validate.y + 2.30, 1.42, 0.43)
    n_val = Rect(validate.x + 0.33, validate.y + 1.52, 1.42, 0.52)
    n_review = Rect(validate.x + 0.33, validate.y + 0.70, 1.42, 0.43)
    node(ax, n_cref, "cross-ref", "complete", ec=PURPLE, fc="white", title_size=6.8)
    node(ax, n_val, "validate", "schema + refs", ec=PURPLE, fc=PURPLE_FILL, title_size=6.8)
    node(ax, n_review, "human review", "approve / reject", ec=PURPLE, fc="white", title_size=6.2)
    arrow(ax, (n_cref.cx, n_cref.bottom), (n_val.cx, n_val.top), color=PURPLE, lw=0.9, ms=8)
    arrow(ax, (n_val.cx, n_val.bottom), (n_review.cx, n_review.top), color=PURPLE, lw=0.9, ms=8)
    note(ax, validate.x + 0.23, validate.y + 0.60, "Router:\nerrors -> earliest owner\nclean / retries exhausted\n-> human interrupt\nreject -> intake / revise", size=4.45)

    # Simulation stage.
    n_sim = Rect(simulation.x + 0.43, simulation.y + 2.26, 1.40, 0.43)
    n_ana = Rect(simulation.x + 0.43, simulation.y + 1.52, 1.40, 0.43)
    n_feed = Rect(simulation.x + 0.43, simulation.y + 0.78, 1.40, 0.43)
    node(ax, n_sim, "simulate", "run EnergyPlus", ec=BLUE, title_size=6.8)
    node(ax, n_ana, "analyze", "parse outputs", ec=BLUE, title_size=6.8)
    node(ax, n_feed, "feedback", "design insight", ec=BLUE, title_size=6.8)
    arrow(ax, (n_sim.cx, n_sim.bottom), (n_ana.cx, n_ana.top), color=BLUE, lw=0.9, ms=8)
    arrow(ax, (n_ana.cx, n_ana.bottom), (n_feed.cx, n_feed.top), color=BLUE, lw=0.9, ms=8)
    note(ax, simulation.x + 0.28, simulation.y + 0.42, "Artifacts: IDF, eplusout.err,\neplusout.end, CSV/tables\nOutputs: EUI, load, comfort,\ncharts and 3D summaries", size=4.55)

    # Only the normal path uses stage-to-stage arrows.
    arrow(ax, (entry.right, main_y), (foundation.left, main_y), ms=12)
    arrow(ax, (foundation.right, main_y), (gate_a.left, gate_a.cy), ms=12)
    arrow(ax, (gate_a.right, gate_a.cy), (envelope.left, gate_a.cy), ms=12)
    arrow(ax, (envelope.right, main_y), (loads.left, main_y), ms=12)
    arrow(ax, (loads.right, main_y), (validate.left, main_y), ms=12)
    arrow(ax, (validate.right, main_y), (simulation.left, main_y), ms=12)

    # Control band: no cross-figure arrows, just routing rules.
    section_rule(ax, 3.55, "Control and recovery rules")
    rag = Rect(0.72, 1.02, 3.90, 1.70)
    state = Rect(4.90, 1.02, 4.20, 1.70)
    repair = Rect(9.38, 1.02, 7.86, 1.70)
    box(ax, rag, fc=GREEN_FILL, ec=GREEN, lw=1.0, radius=0.10)
    box(ax, state, fc=AMBER_FILL, ec=AMBER, lw=1.0, radius=0.10)
    box(ax, repair, fc=RED_FILL, ec=RED, lw=1.0, radius=0.10)

    label(ax, rag.x + 0.20, rag.top - 0.25, "RAG-constrained nodes", size=8.0, weight="bold", ha="left", color=GREEN)
    note(ax, rag.x + 0.20, rag.top - 0.52, "Tool: search_energyplus_reference\nUsed before parameter-heavy generation:\nthermal properties, schedules,\nconstruction layers and HVAC defaults", size=4.9)
    pill(ax, Rect(rag.x + 0.22, rag.y + 0.22, 0.82, 0.30), "material", fc="white", ec=GREEN, color=GREEN)
    pill(ax, Rect(rag.x + 1.12, rag.y + 0.22, 0.82, 0.30), "schedule", fc="white", ec=GREEN, color=GREEN)
    pill(ax, Rect(rag.x + 2.02, rag.y + 0.22, 1.08, 0.30), "construction", fc="white", ec=GREEN, color=GREEN)
    pill(ax, Rect(rag.x + 3.18, rag.y + 0.22, 0.48, 0.30), "hvac", fc="white", ec=GREEN, color=GREEN)

    label(ax, state.x + 0.20, state.top - 0.25, "ConfigState contract", size=8.0, weight="bold", ha="left", color=AMBER)
    note(ax, state.x + 0.20, state.top - 0.52, "Agents mutate cloned local state.\nReducers union objects by identity.\nIDF backing store remains source of truth;\ngates call validate_references().", size=4.9)
    pill(ax, Rect(state.x + 0.22, state.y + 0.22, 1.00, 0.30), "typed slices", fc="white", ec=AMBER, color=AMBER)
    pill(ax, Rect(state.x + 1.35, state.y + 0.22, 0.94, 0.30), "merge", fc="white", ec=AMBER, color=AMBER)
    pill(ax, Rect(state.x + 2.42, state.y + 0.22, 1.25, 0.30), "IDF source", fc="white", ec=AMBER, color=AMBER)

    label(ax, repair.x + 0.20, repair.top - 0.25, "Repair / iteration routing", size=8.0, weight="bold", ha="left", color=RED)
    repair_lines = (
        "A. phase self-repair: local reference errors retry inside the current agent (max 2 rounds)\n"
        "B. upstream back-hop: missing upstream objects route to zone/material/schedule/construction/surface\n"
        "C. global rollback: validate classifies errors and jumps to the earliest owning phase (retry budget)\n"
        "D. design iteration: human rejection or result insight becomes the next revise input"
    )
    label(ax, repair.x + 0.20, repair.top - 0.53, repair_lines, size=5.25, ha="left", va="top", color=MUTED)

    label(
        ax,
        0.55,
        0.45,
        "Only solid arrows are normal execution edges; dense recovery behavior is summarized as routing rules to avoid visual clutter.",
        size=6.4,
        ha="left",
        color=LIGHT_TEXT,
    )

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    out = Path(__file__).resolve().parent.parent / "figures" / "fig2_agent_workflow.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=220, facecolor=BG, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
