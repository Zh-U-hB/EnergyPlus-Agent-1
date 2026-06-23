#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate Figure 1 (overall architecture) for the EnergyPlus-Agent paper.

Reproduces the layered "academic architecture" look of the reference figure:
a landscape canvas with full-width horizontal layer bands (soft fills + a bold
header on the top-left), rounded white inner component boxes inside each band,
solid arrows for the main forward data flow, and a dashed loop-back arrow for
the design feedback cycle. Labels are bilingual (Chinese + English).

Run:
    python paper/scripts/fig1_architecture.py
Output:
    paper/figures/fig1_architecture.png
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# --------------------------------------------------------------------------- #
# Font: Noto Sans CJK SC supports both Chinese and Latin glyphs.
# --------------------------------------------------------------------------- #
_FONT_PATH = os.environ.get(
    "NOTO_CJK_PATH", "/tmp/NotoSansCJKsc-Regular.otf"
)
if os.path.exists(_FONT_PATH):
    CN = FontProperties(fname=_FONT_PATH)
else:  # fall back to default (Chinese may render as boxes if font missing)
    CN = FontProperties()

# --------------------------------------------------------------------------- #
# Palette (aligned to the reference figure: muted, flat, one accent per layer).
# --------------------------------------------------------------------------- #
CANVAS_BG = "#FFFFFF"
LAYER_BORDER = "#BFC7D1"
TEXT_DARK = "#1F2A37"
TEXT_MID = "#4B5563"
ARROW_MAIN = "#6B7280"
ARROW_FEEDBACK = "#E74C3C"

# Each layer: (header_cn, header_en, fill, accent_for_header)
LAYERS = [
    ("用户输入层", "User Input", "#F4F6F9", "#475569"),
    ("输入解析层", "Intent Parsing", "#EAF2FB", "#2F6FB0"),
    ("RAG 知识层", "Retrieval-Augmented Control", "#EAF5EE", "#3F8A5A"),
    ("智能体编排层", "Agent Orchestration", "#FBF1E8", "#C8794A"),
    ("仿真与结果层", "Simulation & Results", "#F2ECFA", "#7A4FB6"),
]


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #
@dataclass
class Box:
    """A rounded inner component box."""
    x: float          # center x
    y: float          # center y
    w: float
    h: float
    title: str        # bold first line
    subtitle: str     # smaller second line (optional)
    accent: str = "#2F6FB0"

    def left(self) -> float:
        return self.x - self.w / 2

    def top(self) -> float:
        return self.y + self.h / 2

    def bottom(self) -> float:
        return self.y - self.h / 2

    def right(self) -> float:
        return self.x + self.w / 2


def round_box(ax, x, y, w, h, *, facecolor="#FFFFFF",
              edgecolor=LAYER_BORDER, lw=1.0, pad=0.0, rounding=0.02,
              shadow=False):
    """Draw a rounded rectangle (FancyBboxPatch) by its lower-left corner."""
    if shadow:
        sh = FancyBboxPatch(
            (x + 0.05, y - 0.05),
            w - 2 * pad,
            h - 2 * pad,
            boxstyle=f"round,pad={pad},rounding_size={rounding}",
            linewidth=0, edgecolor="none", facecolor="#00000022", zorder=1)
        ax.add_patch(sh)
    patch = FancyBboxPatch(
        (x + pad, y + pad),
        w - 2 * pad,
        h - 2 * pad,
        boxstyle=f"round,pad={pad},rounding_size={rounding}",
        linewidth=lw,
        edgecolor=edgecolor,
        facecolor=facecolor,
        zorder=2,
    )
    ax.add_patch(patch)


def draw_layer_band(ax, x0, y0, w, h, header_cn, header_en, fill, accent):
    """Full-width soft-filled band with a header chip on the top-left."""
    round_box(ax, x0, y0, w, h, facecolor=fill, edgecolor=LAYER_BORDER,
              lw=1.3, rounding=0.012)
    # header chip (small colored rounded label)
    chip_w, chip_h = 3.5, 0.42
    round_box(ax, x0 + 0.22, y0 + h - chip_h - 0.20, chip_w, chip_h,
              facecolor=accent, edgecolor="none", rounding=0.08)
    ax.text(x0 + 0.22 + chip_w / 2, y0 + h - chip_h / 2 - 0.02,
            f"{header_cn}  {header_en}",
            ha="center", va="center", color="white", fontsize=9.5,
            fontproperties=CN, fontweight="bold", zorder=3)


def draw_component_box(ax, b: Box):
    """White rounded component box with bold title + small subtitle."""
    round_box(ax, b.left(), b.bottom(), b.w, b.h,
              facecolor="#FFFFFF", edgecolor=b.accent, lw=1.3, rounding=0.05,
              shadow=True)
    ax.text(b.x, b.y + (0.20 if b.subtitle else 0.0),
            b.title, ha="center", va="center",
            color=TEXT_DARK, fontsize=10.2, fontproperties=CN,
            fontweight="bold", zorder=3)
    if b.subtitle:
        ax.text(b.x, b.y - 0.24, b.subtitle, ha="center", va="center",
                color=TEXT_MID, fontsize=7.9, fontproperties=CN, zorder=3)


def arrow(ax, p1, p2, *, color=ARROW_MAIN, ls="-", lw=1.7,
          label=None, label_offset=(0.0, 0.14), rad=0.0, label_color=None):
    """Styled arrow between two (x, y) points with an optional text label."""
    conn = f"arc3,rad={rad}" if rad else "arc3"
    ax.add_patch(FancyArrowPatch(
        p1, p2, arrowstyle="-|>", mutation_scale=15,
        color=color, lw=lw, linestyle=ls, zorder=4,
        connectionstyle=conn,
    ))
    if label:
        mx = (p1[0] + p2[0]) / 2 + label_offset[0]
        my = (p1[1] + p2[1]) / 2 + label_offset[1]
        ax.text(mx, my, label, ha="center", va="center",
                color=label_color or TEXT_MID, fontsize=7.4,
                fontproperties=CN, zorder=5,
                bbox=dict(boxstyle="round,pad=0.18", fc="white",
                          ec="none", alpha=0.9))


# --------------------------------------------------------------------------- #
# Figure layout
# --------------------------------------------------------------------------- #
W, H = 16.0, 11.0          # canvas units
MARGIN_X = 0.6
band_x0 = MARGIN_X
band_w = W - 2 * MARGIN_X
band_h = 1.62
band_gap = 0.46

fig, ax = plt.subplots(figsize=(16, 11), dpi=150)
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.axis("off")
fig.patch.set_facecolor(CANVAS_BG)

# ---- Designer node (top, centered) ----
designer_y = H - 0.75
designer = Box(W / 2, designer_y, 2.4, 0.72,
               "设计者  Designer", "Human in the loop", "#2B2B2B")
round_box(ax, designer.left(), designer.bottom(), designer.w, designer.h,
          facecolor="#FFFFFF", edgecolor="#2B2B2B", lw=1.8, rounding=0.12)
ax.text(designer.x, designer.y + 0.1, designer.title, ha="center",
        va="center", color=TEXT_DARK, fontsize=9.5, fontproperties=CN,
        fontweight="bold", zorder=3)
ax.text(designer.x, designer.y - 0.2, designer.subtitle, ha="center",
        va="center", color=TEXT_MID, fontsize=7.0, fontproperties=CN, zorder=3)

# ---- Layer bands (top-down) ----
# Place bands below the designer node.
top_band_top = designer_y - 0.95
centers_y = []  # remember the band vertical center for arrows
band_rects = []
cur_top = top_band_top
for i, (hcn, hen, fill, accent) in enumerate(LAYERS):
    y0 = cur_top - band_h          # lower-left y
    draw_layer_band(ax, band_x0, y0, band_w, band_h,
                    hcn, hen, fill, accent)
    centers_y.append(y0 + band_h / 2)
    band_rects.append((band_x0, y0, band_w, band_h, accent))
    cur_top = y0 - band_gap

# ---- Component boxes inside each band ----
bw, bh = 2.75, 0.92
cy_band = {i: c for i, c in enumerate(centers_y)}

# Layer 1: User Input — three boxes
l1 = [
    Box(4.6, cy_band[0], bw, bh, "自然语言描述",
        "Natural-language prompt", "#475569"),
    Box(8.0, cy_band[0], bw, bh, "建筑图纸",
        "Drawings (plan/elevation/section)", "#475569"),
    Box(11.4, cy_band[0], bw, bh, "气象文件 EPW",
        "Weather file", "#475569"),
]
# Layer 2: Intent Parsing
intake = Box(6.3, cy_band[1], 3.2, bh, "多模态大语言模型",
             "Multimodal LLM", "#2F6FB0")
intent = Box(10.9, cy_band[1], 3.2, bh, "结构化建筑意图",
             "Structured output (IntakeOutput)", "#2F6FB0")
# Layer 3: RAG
ref = Box(6.3, cy_band[2], 3.2, bh, "EnergyPlus 参考库",
          "Materials / Constructions / Schedules / Design days", "#3F8A5A")
retr = Box(10.9, cy_band[2], 3.2, bh, "向量检索",
           "Vector retrieval (Qdrant + Gemini)", "#3F8A5A")
# Layer 4: Agent Orchestration — four evenly spaced boxes in a row
_l4w = 2.65
_l4_centers = [3.45, 7.05, 10.65, 14.05]
orch = Box(_l4_centers[0], cy_band[3], _l4w, bh, "多阶段 Agent 编排",
           "LangGraph workflow", "#C8794A")
mcp = Box(_l4_centers[1], cy_band[3], _l4w, bh, "MCP 工具层",
          "Structured CRUD · 10 object types", "#C8794A")
cfg = Box(_l4_centers[2], cy_band[3], _l4w, bh, "中心配置状态",
          "ConfigState (idfpy-backed)", "#C8794A")
val = Box(_l4_centers[3], cy_band[3], _l4w, bh, "多层正确性保障",
          "Schema + cross-ref + self-repair", "#C8794A")
# Layer 5: Simulation & Results
idf = Box(4.6, cy_band[4], bw, bh, "IDF 生成",
          "IDF generation", "#7A4FB6")
ep = Box(8.0, cy_band[4], bw, bh, "EnergyPlus 仿真",
         "EnergyPlus simulation", "#7A4FB6")
anz = Box(11.4, cy_band[4], bw, bh, "结果解析与可视化",
          "Energy / EUI / comfort / peak / 3D solar", "#7A4FB6")

for b in l1 + [intake, intent, ref, retr, orch, mcp, cfg, val, idf, ep, anz]:
    draw_component_box(ax, b)

# ---- Arrows: designer -> inputs ----
arrow(ax, (designer.x, designer.bottom()),
      (l1[0].x, l1[0].top()), label="输入 input", rad=0.0)
arrow(ax, (designer.x - 0.5, designer.bottom()),
      (l1[1].x, l1[1].top()), ls=(0, (4, 3)))
arrow(ax, (designer.x + 0.5, designer.bottom()),
      (l1[2].x, l1[2].top()), ls=(0, (4, 3)))

# Layer 1 -> Layer 2 (text + drawings into LLM)
arrow(ax, (l1[0].x, l1[0].bottom()), (intake.x, intake.top()))
arrow(ax, (l1[1].x, l1[1].bottom()), (intake.x + 0.6, intake.top()),
      ls=(0, (4, 3)))
# EPW bypasses to IDF generation
arrow(ax, (l1[2].x, l1[2].bottom()), (idf.x + 1.0, idf.top()),
      ls=(0, (4, 3)), label="EPW", label_offset=(0.0, 0.0))

# Layer 2 internal + -> RAG
arrow(ax, (intake.right(), intake.y), (intent.left(), intent.y),
      label="结构化输出")
arrow(ax, (intent.x, intent.bottom()), (retr.x, retr.top()),
      label="专业参数取值依据", label_offset=(1.6, 0.05), rad=-0.12)
# RAG internal
arrow(ax, (ref.right(), ref.y), (retr.left(), ref.y), label="索引")

# RAG -> orchestration
arrow(ax, (retr.x, retr.bottom()), (orch.x, orch.top()),
      label="检索记录", label_offset=(-1.8, 0.05), rad=0.12)

# Layer 4 internal chain
arrow(ax, (orch.right(), orch.y), (mcp.left(), mcp.y), label="调用工具")
arrow(ax, (mcp.right(), mcp.y), (cfg.left(), cfg.y), label="读写对象")
arrow(ax, (cfg.right(), cfg.y), (val.left(), val.y), label="校验")

# Layer 4 -> Layer 5
arrow(ax, (val.x - 0.5, val.bottom()), (idf.x + 1.0, idf.top()),
      label="可运行模型", label_offset=(2.6, -0.05))
# Layer 5 internal
arrow(ax, (idf.right(), idf.y), (ep.left(), ep.y))
arrow(ax, (ep.right(), ep.y), (anz.left(), anz.y))

# ---- Feedback loop (dashed): results -> designer ----
fb_start = (anz.right(), anz.y)
fb_mid1 = (W - 0.25, anz.y)
fb_mid2 = (W - 0.25, designer_y)
fb_end = (designer.right(), designer.y)
arrow(ax, fb_start, fb_mid1, color=ARROW_FEEDBACK,
      ls=(0, (5, 4)), lw=1.6)
arrow(ax, fb_mid1, fb_mid2, color=ARROW_FEEDBACK,
      ls=(0, (5, 4)), lw=1.6)
arrow(ax, fb_mid2, fb_end, color=ARROW_FEEDBACK,
      ls=(0, (5, 4)), lw=1.6,
      label="设计反馈 Design feedback（驱动下一轮迭代）",
      label_offset=(-4.2, -0.55), label_color=ARROW_FEEDBACK)

# Self-repair dashed: validation errors -> orchestration (within L4)
arrow(ax, (val.x, val.top() + 0.02), (orch.x, orch.top() + 0.02),
      color="#C8794A", ls=(0, (3, 3)), lw=1.2, rad=-0.35,
      label="校验错误回灌自修复", label_offset=(0.0, 0.16),
      label_color="#A85A2A")

# ---- Caption / legend strip at bottom ----
ax.text(W / 2, 0.32,
        "图 1  EnergyPlus-Agent 总体架构  |  实线 = 主数据流，"
        "虚线 = 反馈回路",
        ha="center", va="center", fontsize=8.5, color=TEXT_MID,
        fontproperties=CN)

plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
out = os.path.join(os.path.dirname(__file__), "..", "figures",
                   "fig1_architecture.png")
out = os.path.normpath(out)
plt.savefig(out, dpi=200, facecolor=CANVAS_BG, bbox_inches="tight",
            pad_inches=0.15)
print(f"saved: {out}")
