#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate Figure 1 for the EnergyPlus-Agent paper.

The figure intentionally follows the earlier manuscript style: a left layer
index column, dashed horizontal separators, light academic module panels, small
tool cards, and a dashed iterative feedback loop. The content has been updated
to match the current implementation:

    intake/revise -> [zone, material, schedule] -> cross_ref_foundations
    -> construction -> surface -> fenestration -> [hvac, people, lights]
    -> cross_ref_complete -> validate -> simulate -> analyze

Run:
    python paper/scripts/fig1_architecture.py
Output:
    paper/figures/fig1_architecture.png
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Wedge


def _font() -> FontProperties:
    """Pick a CJK-capable font when available, with a portable fallback."""
    candidates = [
        os.environ.get("NOTO_CJK_PATH", ""),
        r"C:/Windows/Fonts/msyh.ttc",
        r"C:/Windows/Fonts/simhei.ttf",
        r"C:/Windows/Fonts/simsun.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/tmp/NotoSansCJKsc-Regular.otf",
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


# Canvas and palette tuned to the provided reference figure.
W, H = 16.0, 10.5
LEFT_W = 2.55
CONTENT_X0 = LEFT_W + 0.18
CONTENT_X1 = W - 0.18
TOP, BOTTOM = 10.25, 0.25
ROW_H = (TOP - BOTTOM) / 7

BG = "#FFFFFF"
LEFT_BG = "#F1F5F9"
GRID = "#2F2F2F"
TEXT = "#111111"
MUTED = "#333333"
LINE = "#111111"
ARROW = "#111111"
BLUE = "#355FA8"
BLUE_FILL = "#F1F6FF"
GREEN = "#5B7F58"
GREEN_FILL = "#F2F8F1"
AMBER = "#A87938"
AMBER_FILL = "#FFF8E8"
PURPLE = "#8A72B6"
PURPLE_FILL = "#F7F3FF"
RESULT_BLUE = "#4F78A8"
RESULT_FILL = "#F2F8FF"
RED = "#D34A3A"


def row_rect(index: int) -> Rect:
    """Return row rectangle for 0-based top-to-bottom layer index."""
    y = TOP - (index + 1) * ROW_H
    return Rect(0, y, W, ROW_H)


def content_rect(index: int, pad_x: float = 0.1, pad_y: float = 0.16) -> Rect:
    r = row_rect(index)
    return Rect(CONTENT_X0 + pad_x, r.y + pad_y, CONTENT_X1 - CONTENT_X0 - 2 * pad_x, r.h - 2 * pad_y)


def rounded(ax, rect: Rect, *, fc: str = "white", ec: str = LINE, lw: float = 1.0,
            radius: float = 0.055, ls: str | tuple = "-", z: int = 2) -> FancyBboxPatch:
    patch = FancyBboxPatch(
        (rect.x, rect.y),
        rect.w,
        rect.h,
        boxstyle=f"round,pad=0.012,rounding_size={radius}",
        facecolor=fc,
        edgecolor=ec,
        linewidth=lw,
        linestyle=ls,
        zorder=z,
    )
    ax.add_patch(patch)
    return patch


def label(ax, x: float, y: float, text: str, *, size: float = 8.0,
          weight: str = "normal", ha: str = "center", va: str = "center",
          color: str = TEXT, style: str = "normal", z: int = 5) -> None:
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
    )


def arrow(ax, start: tuple[float, float], end: tuple[float, float], *,
          color: str = ARROW, lw: float = 1.1, ls: str | tuple = "-",
          ms: float = 10, rad: float = 0.0, z: int = 6) -> None:
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=ms,
            linewidth=lw,
            linestyle=ls,
            color=color,
            connectionstyle=f"arc3,rad={rad}",
            zorder=z,
        )
    )


def double_arrow(ax, start: tuple[float, float], end: tuple[float, float], *,
                 color: str = ARROW, lw: float = 1.0, ms: float = 10) -> None:
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="<->",
            mutation_scale=ms,
            linewidth=lw,
            color=color,
            zorder=6,
        )
    )


def draw_user_icon(ax, x: float, y: float, scale: float = 1.0) -> None:
    ax.add_patch(Circle((x, y + 0.12 * scale), 0.105 * scale, color="black", zorder=6))
    ax.add_patch(Wedge((x, y - 0.08 * scale), 0.23 * scale, 0, 180, color="black", zorder=6))


def mini_card(ax, rect: Rect, title: str, subtitle: str = "", *,
              ec: str = BLUE, fc: str = "#FFFFFF", title_size: float = 6.4) -> None:
    rounded(ax, rect, fc=fc, ec=ec, lw=0.8, radius=0.04)
    label(ax, rect.cx, rect.cy + (0.08 if subtitle else 0.0), title,
          size=title_size, weight="bold")
    if subtitle:
        label(ax, rect.cx, rect.cy - 0.16, subtitle, size=5.4, color=MUTED)


def section_box(ax, rect: Rect, title: str, *, ec: str, fc: str, title_y: float = 0.16) -> None:
    rounded(ax, rect, fc=fc, ec=ec, lw=1.0, radius=0.06)
    label(ax, rect.cx, rect.top - title_y, title, size=8.4, weight="bold")


def draw_layer_grid(ax) -> None:
    # Outer frame and left layer column
    ax.add_patch(plt.Rectangle((0, BOTTOM), W, TOP - BOTTOM, facecolor=BG, edgecolor=GRID, linewidth=1.0, zorder=0))
    ax.add_patch(plt.Rectangle((0, BOTTOM), LEFT_W, TOP - BOTTOM, facecolor=LEFT_BG, edgecolor=GRID, linewidth=0.9, zorder=1))
    ax.plot([LEFT_W, LEFT_W], [BOTTOM, TOP], color=GRID, linewidth=0.9, zorder=2)

    layer_labels = [
        "1. Interaction Layer",
        "2. Agent Layer\n(LLM + MCP Tools)",
        "3. Knowledge Layer\n(RAG)",
        "4. State Layer\n(ConfigState)",
        "5. Validation & Export\nLayer",
        "6. Simulation Layer\n(EnergyPlus)",
        "7. Result & Feedback\nLayer",
    ]
    for i, text in enumerate(layer_labels):
        r = row_rect(i)
        if i > 0:
            ax.plot([0, W], [r.top, r.top], color=GRID, linewidth=0.8, linestyle=(0, (5, 4)), zorder=2)
        label(ax, LEFT_W / 2, r.cy, text, size=8.2, weight="bold")


def draw_interaction(ax) -> Rect:
    r = content_rect(0, pad_x=0.75, pad_y=0.23)
    user = Rect(r.x + 0.25, r.y + 0.05, r.w - 0.5, r.h - 0.1)
    rounded(ax, user, fc="#FFFFFF", ec=LINE, lw=0.8, radius=0.05)
    draw_user_icon(ax, user.x + 0.92, user.cy, 1.0)
    label(ax, user.x + 2.35, user.cy + 0.16, "User", size=10.8, weight="bold")
    label(ax, user.x + 2.35, user.cy - 0.15, "(Architect / Designer / Engineer)", size=7.3)
    label(ax, user.x + 6.05, user.cy + 0.20, "Natural Language Requirement + Drawings + EPW",
          size=8.3, weight="bold", ha="left")
    label(ax, user.x + 6.05, user.cy - 0.16,
          '"Design a five-zone office in Shenzhen with low energy consumption."',
          size=7.1, style="italic", ha="left")
    return user


def draw_agent_layer(ax) -> tuple[Rect, Rect]:
    r = content_rect(1, pad_x=0.10, pad_y=0.16)
    agent = Rect(r.x, r.y + 0.02, 4.85, r.h - 0.04)
    toolset = Rect(agent.right + 0.72, r.y + 0.02, r.right - agent.right - 0.72, r.h - 0.04)

    section_box(ax, agent, "LLM Agent  (LangGraph workflow)", ec=BLUE, fc=BLUE_FILL, title_y=0.11)
    section_box(ax, toolset, "MCP  (Model Context Protocol) Toolset", ec=BLUE, fc=BLUE_FILL, title_y=0.11)

    chips = [
        ("Intake /\nRevise", agent.x + 0.28),
        ("Zone + Material\n+ Schedule", agent.x + 1.36),
        ("Cross-ref\nFoundations", agent.x + 2.58),
        ("Envelope:\nConstruction -> Surface -> Window", agent.x + 0.62),
        ("Loads:\nHVAC + People + Lights", agent.x + 2.16),
        ("Validate ->\nSimulate -> Analyze", agent.x + 3.62),
    ]
    chip_w = [0.85, 1.06, 1.06, 1.35, 1.25, 1.18]
    chip_y_top = agent.y + 0.41
    chip_y_bot = agent.y + 0.08
    for idx, ((text, x), w) in enumerate(zip(chips[:3], chip_w[:3])):
        mini_card(ax, Rect(x, chip_y_top, w, 0.30), text, ec=BLUE, fc="#FFFFFF", title_size=4.9)
        if idx < 2:
            arrow(ax, (x + w + 0.02, chip_y_top + 0.15), (chips[idx + 1][1] - 0.02, chip_y_top + 0.15), lw=0.8, ms=7)
    for idx, ((text, x), w) in enumerate(zip(chips[3:], chip_w[3:])):
        mini_card(ax, Rect(x, chip_y_bot, w, 0.30), text, ec=BLUE, fc="#FFFFFF", title_size=4.6)
        if idx < 2:
            arrow(ax, (x + w + 0.02, chip_y_bot + 0.15), (chips[4 + idx][1] - 0.02, chip_y_bot + 0.15), lw=0.8, ms=7)
    arrow(ax, (chips[2][1] + chip_w[2] / 2, chip_y_top), (chips[3][1] + chip_w[3] / 2, chip_y_bot + 0.30), lw=0.8, ms=7, rad=0.08)

    tool_titles = [
        ("Building\nSite", "B"),
        ("Zone\nTool", "Z"),
        ("Material\nTool", "M"),
        ("Construction\nTool", "C"),
        ("Surface\nTool", "S"),
        ("Window\nTool", "W"),
        ("Schedule\nTool", "Sc"),
        ("HVAC\nTool", "HV"),
        ("People /\nLights", "L"),
        ("Workflow /\nValidation", "WF"),
    ]
    card_gap = 0.08
    card_w = (toolset.w - 0.42 - card_gap * (len(tool_titles) - 1)) / len(tool_titles)
    card_h = 0.60
    x = toolset.x + 0.21
    y = toolset.y + 0.12
    for title, icon in tool_titles:
        card = Rect(x, y, card_w, card_h)
        rounded(ax, card, fc="#FFFFFF", ec=BLUE, lw=0.75, radius=0.04)
        label(ax, card.cx, card.top - 0.20, icon, size=8.6, weight="bold")
        label(ax, card.cx, card.y + 0.18, title, size=5.0, weight="bold")
        x += card_w + card_gap

    double_arrow(ax, (agent.right + 0.08, agent.cy), (toolset.left - 0.08, toolset.cy), lw=0.9)
    label(ax, agent.right + 0.36, agent.cy + 0.20, "MCP\nProtocol", size=5.8)
    return agent, toolset


def draw_knowledge_layer(ax) -> tuple[Rect, Rect]:
    r = content_rect(2, pad_x=0.10, pad_y=0.16)
    rag = Rect(r.x, r.y + 0.04, 4.15, r.h - 0.08)
    kb = Rect(rag.right + 0.48, r.y + 0.04, r.right - rag.right - 0.48, r.h - 0.08)
    section_box(ax, rag, "RAG Pipeline", ec=GREEN, fc=GREEN_FILL)
    section_box(ax, kb, "Knowledge Base", ec=GREEN, fc=GREEN_FILL)

    steps = ["Query\nUnderstanding", "Retrieval", "Re-ranking", "Context\nGeneration"]
    sw, gap = 0.82, 0.16
    x = rag.x + 0.22
    y = rag.y + 0.22
    for i, title in enumerate(steps):
        mini_card(ax, Rect(x, y, sw, 0.55), title, ec=GREEN, title_size=5.2)
        if i < len(steps) - 1:
            arrow(ax, (x + sw + 0.01, y + 0.275), (x + sw + gap - 0.02, y + 0.275), lw=0.75, ms=7)
        x += sw + gap

    entries = [
        "EnergyPlus\nDocs",
        "IDD\nReference",
        "Materials\nDatabase",
        "Construction\nLibrary",
        "Schedule /\nDesign Days",
        "SQLite\nStorage",
        "Qdrant\nVector DB",
    ]
    ew, egap = 0.86, 0.13
    x = kb.x + 0.20
    y = kb.y + 0.19
    for i, title in enumerate(entries):
        mini_card(ax, Rect(x, y, ew, 0.58), title, ec=GREEN, title_size=4.9)
        if i == 4:
            ax.plot([x + ew + egap / 2, x + ew + egap / 2], [y + 0.03, y + 0.55],
                    color=GREEN, linestyle=(0, (4, 3)), linewidth=0.8, zorder=5)
        x += ew + egap

    double_arrow(ax, (rag.right + 0.05, rag.cy), (kb.left - 0.05, kb.cy), lw=0.9)
    label(ax, kb.x + 0.72, kb.bottom + 0.06,
          "Used by Material / Construction / Schedule / HVAC agents", size=5.6, color=MUTED, ha="left")
    return rag, kb


def draw_state_layer(ax) -> Rect:
    r = content_rect(3, pad_x=0.10, pad_y=0.20)
    state = Rect(r.x, r.y, r.w, r.h)
    section_box(ax, state, "ConfigState  (idfpy-backed Building Configuration State)", ec=AMBER, fc=AMBER_FILL, title_y=0.20)
    items = [
        "Building /\nSite",
        "Zones",
        "Materials",
        "Constructions",
        "Surfaces",
        "Fenestrations",
        "Schedules",
        "HVAC",
        "People /\nLights",
        "Output\nVariables",
    ]
    gap = 0.16
    iw = (state.w - 0.55 - gap * (len(items) - 1)) / len(items)
    x = state.x + 0.27
    y = state.y + 0.12
    for item in items:
        mini_card(ax, Rect(x, y, iw, 0.30), item, ec=AMBER, fc="#FFFDF7", title_size=4.7)
        rounded(ax, Rect(x, y, iw, 0.30), fc="none", ec=AMBER, lw=0.55, radius=0.035, ls=(0, (4, 3)), z=7)
        x += iw + gap
    return state


def draw_validation_layer(ax) -> tuple[Rect, Rect, Rect]:
    r = content_rect(4, pad_x=0.10, pad_y=0.16)
    v = Rect(r.x, r.y + 0.03, 3.6, r.h - 0.06)
    repair = Rect(v.right + 0.35, r.y + 0.03, 4.6, r.h - 0.06)
    export = Rect(repair.right + 0.35, r.y + 0.03, r.right - repair.right - 0.35, r.h - 0.06)
    section_box(ax, v, "Validation", ec=PURPLE, fc=PURPLE_FILL)
    label(ax, v.x + 0.22, v.cy + 0.05,
          "• Structured output / Pydantic Schema\n"
          "• Geometry and surface closure checks\n"
          "• Cross-reference validation",
          size=6.0, ha="left")

    section_box(ax, repair, "Self-Repair + Human Review", ec=PURPLE, fc=PURPLE_FILL)
    sub = [
        "Phase-local\nself repair",
        "Directed\nrollback",
        "Human-in-\nthe-loop",
        "EnergyPlus\n.err feedback",
    ]
    sw, gap = 0.90, 0.18
    x = repair.x + 0.30
    for item in sub:
        mini_card(ax, Rect(x, repair.y + 0.20, sw, 0.48), item, ec=PURPLE, title_size=4.9)
        x += sw + gap

    section_box(ax, export, "IDF Export", ec=PURPLE, fc=PURPLE_FILL)
    label(ax, export.x + 0.25, export.cy - 0.02,
          "• WorkflowTool.save_idf()\n"
          "• IDF generation from ConfigState\n"
          "• Consistency gate before run",
          size=6.0, ha="left")
    arrow(ax, (v.right + 0.05, v.cy), (repair.left - 0.05, repair.cy), lw=0.9)
    arrow(ax, (repair.right + 0.05, repair.cy), (export.left - 0.05, export.cy), lw=0.9)
    return v, repair, export


def draw_simulation_layer(ax) -> Rect:
    r = content_rect(5, pad_x=0.70, pad_y=0.23)
    sim = Rect(r.x, r.y + 0.05, r.w, r.h - 0.10)
    rounded(ax, sim, fc=RESULT_FILL, ec=RESULT_BLUE, lw=0.9, radius=0.05)
    label(ax, sim.x + 2.40, sim.cy + 0.12, "EnergyPlus Simulation Engine", size=9.2, weight="bold")
    label(ax, sim.x + 2.40, sim.cy - 0.17, "energyplus -x -w EPW -d output IDF", size=6.1)
    metric_titles = ["Energy / EUI", "Thermal Comfort", "Peak Load", "Surface Solar", "Output Files"]
    mw, gap = 1.36, 0.20
    x = sim.x + 4.45
    y = sim.y + 0.23
    for title in metric_titles:
        mini_card(ax, Rect(x, y, mw, 0.38), title, ec=RESULT_BLUE, title_size=5.3)
        x += mw + gap
    label(ax, sim.x + 0.70, sim.cy, "EnergyPlus", size=8.4, weight="bold", color="#C64232")
    return sim


def draw_result_layer(ax) -> tuple[Rect, Rect, Rect]:
    r = content_rect(6, pad_x=0.25, pad_y=0.20)
    viz = Rect(r.x, r.y + 0.05, 4.15, r.h - 0.10)
    fb = Rect(viz.right + 0.38, r.y + 0.05, 4.10, r.h - 0.10)
    refine = Rect(fb.right + 0.38, r.y + 0.05, r.right - fb.right - 0.38, r.h - 0.10)
    section_box(ax, viz, "Results Visualization", ec=RESULT_BLUE, fc=RESULT_FILL)
    label(ax, viz.cx, viz.cy - 0.04, "Dashboard   Charts   Reports   3D Model", size=6.2)
    label(ax, viz.cx, viz.y + 0.20, "eplusout.csv / eplustbl / eplusout.eso", size=5.4, color=MUTED)

    section_box(ax, fb, "Feedback to User", ec=RESULT_BLUE, fc=RESULT_FILL)
    label(ax, fb.cx, fb.cy - 0.02,
          "Insights, warnings, design trade-offs,\nand optimization suggestions.",
          size=6.0)

    section_box(ax, refine, "Iterative Refinement", ec=RESULT_BLUE, fc=RESULT_FILL)
    label(ax, refine.cx, refine.cy - 0.02,
          "User feedback -> revise node -> ConfigState update\n-> re-validation -> re-simulation",
          size=5.8)
    return viz, fb, refine


def main() -> None:
    fig, ax = plt.subplots(figsize=(16, 10.5), dpi=170)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")

    draw_layer_grid(ax)
    user = draw_interaction(ax)
    agent, toolset = draw_agent_layer(ax)
    rag, kb = draw_knowledge_layer(ax)
    state = draw_state_layer(ax)
    validation, repair, export = draw_validation_layer(ax)
    sim = draw_simulation_layer(ax)
    viz, feedback, refine = draw_result_layer(ax)

    # Main flow arrows.
    arrow(ax, (user.cx, user.bottom), (agent.cx, agent.top + 0.01), lw=1.1)
    arrow(ax, (toolset.cx, toolset.bottom), (state.cx, state.top + 0.01), lw=1.1)
    arrow(ax, (agent.cx, agent.bottom), (rag.x + 1.15, rag.top + 0.01), lw=1.0)
    arrow(ax, (kb.cx, kb.bottom), (state.cx, state.top + 0.01), lw=1.0)
    arrow(ax, (state.cx, state.bottom), (repair.cx, repair.top + 0.01), lw=1.1)
    arrow(ax, (export.cx, export.bottom), (sim.cx, sim.top + 0.01), lw=1.1)
    arrow(ax, (sim.cx, sim.bottom), (feedback.cx, feedback.top + 0.01), lw=1.1)
    arrow(ax, (viz.right + 0.06, viz.cy), (feedback.left - 0.06, feedback.cy), lw=0.9)
    arrow(ax, (feedback.right + 0.06, feedback.cy), (refine.left - 0.06, refine.cy), lw=0.9)

    # RAG context returns to the RAG-enabled phase agents.
    arrow(ax, (rag.right - 0.30, rag.top), (agent.x + 2.45, agent.bottom + 0.01), lw=0.9, rad=-0.08)
    label(ax, agent.x + 2.75, rag.top + 0.08, "retrieved context", size=5.4, color=MUTED)

    # Validation errors are routed back to owning agents.
    arrow(ax, (validation.cx, validation.top), (agent.x + 3.50, agent.bottom + 0.01),
          color=RED, lw=0.9, ls=(0, (4, 3)), rad=-0.15)
    label(ax, validation.cx + 0.95, validation.top + 0.18, "validation errors -> self-repair", size=5.3, color=RED)

    # Iterative feedback loop in the same visual language as the reference.
    right_x = W - 0.12
    arrow(ax, (refine.right, refine.cy), (right_x, refine.cy), color=RED, lw=1.0, ls=(0, (5, 4)), ms=8)
    ax.plot([right_x, right_x], [refine.cy, user.cy], color=RED, linewidth=1.0, linestyle=(0, (5, 4)), zorder=5)
    arrow(ax, (right_x, user.cy), (user.right, user.cy), color=RED, lw=1.0, ls=(0, (5, 4)), ms=8)

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    out = Path(__file__).resolve().parent.parent / "figures" / "fig1_architecture.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=220, facecolor=BG, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
