"""Render a bird's-eye (3-D isometric) PNG of an EnergyPlus IDF.

Used by the robustness benchmark to capture a quick visual snapshot of
the building the agent produced. Loads ``src/results/idf_geometry.py``
*directly by file path* (via importlib) rather than ``from src.results
import ...``: importing the ``src.results`` package executes its
``__init__.py`` which pulls in the results parser and, transitively,
``idfpy`` — and ``import idfpy`` is slow / can hang in this environment.
The geometry parser itself is pure-text (re + dataclasses) and has no
idfpy dependency, so loading the module file directly is both safe and fast.

Public API: ``render_top_view(idf_path, out_png, dpi=150) -> Path``
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: must be set before pyplot import
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import to_rgba
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


def _load_geometry_module():
    """Load src/results/idf_geometry.py as an isolated module (no package init)."""
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    mod_path = repo_root / "src" / "results" / "idf_geometry.py"
    mod_name = "_idf_geometry_isolated"
    spec = importlib.util.spec_from_file_location(mod_name, mod_path)
    assert spec and spec.loader, f"cannot load spec for {mod_path}"
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec: @dataclass needs to look up
    # cls.__module__ in sys.modules during class processing, and a missing
    # entry raises AttributeError('NoneType' has no __dict__).
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


_geo = _load_geometry_module()
parse_idf_geometry = _geo.parse_idf_geometry

# Surface-type -> (face color, alpha). Floors nearly transparent so walls
# and roof read clearly in the isometric view.
_TYPE_STYLE: dict[str, tuple[str, float]] = {
    "wall": ("#9ecae1", 0.55),
    "roof": ("#fdd0a2", 0.70),
    "ceiling": ("#e7e7e7", 0.35),
    "floor": ("#3182bd", 0.12),
}


def _zone_color(zone_index: int) -> tuple[float, float, float]:
    """Pick a stable color per zone from the tab20 colormap."""
    import matplotlib as mpl

    cmap = mpl.colormaps["tab20"]
    return cmap(zone_index % 20)[:3]


def render_top_view(
    idf_path: Path | str, out_png: Path | str, dpi: int = 150
) -> Path:
    """Render an isometric PNG of the building in *idf_path* to *out_png*.

    Faces are colored by thermal zone (so zones are visually separable),
    with edge lines drawn on every polygon. Axes are equal-scaled in x/y/z.
    Returns the output path. Raises if the IDF has no parseable surfaces.
    """
    idf_path = Path(idf_path)
    out_png = Path(out_png)
    zones = parse_idf_geometry(idf_path)
    if not zones:
        raise ValueError(f"no zones/surfaces parsed from {idf_path}")

    fig = plt.figure(figsize=(9, 8))
    ax = fig.add_subplot(111, projection="3d")

    all_xs: list[float] = []
    all_ys: list[float] = []
    all_zs: list[float] = []

    # Sort zone names for stable coloring.
    for zi, zone_name in enumerate(sorted(zones)):
        zone_color = _zone_color(zi)
        for surf in zones[zone_name].surfaces:
            verts = surf.vertices
            if len(verts) < 3:
                continue
            base_alpha = _TYPE_STYLE.get(surf.surface_type.lower(), ("#cccccc", 0.5))[1]
            rgba = to_rgba(zone_color, alpha=base_alpha)
            ax.add_collection3d(
                Poly3DCollection(
                    [verts],
                    facecolors=[rgba],
                    edgecolors=("#333333",),
                    linewidths=0.4,
                )
            )
            for x, y, z in verts:
                all_xs.append(x)
                all_ys.append(y)
                all_zs.append(z)

    if not all_xs:
        raise ValueError(f"no drawable surfaces in {idf_path}")

    xs = np.array(all_xs)
    ys = np.array(all_ys)
    zs = np.array(all_zs)
    pad_xy = max(1.0, (max(xs.max() - xs.min(), ys.max() - ys.min())) * 0.05)
    pad_z = max(1.0, (zs.max() - zs.min()) * 0.10)

    ax.set_xlim(xs.min() - pad_xy, xs.max() + pad_xy)
    ax.set_ylim(ys.min() - pad_xy, ys.max() + pad_xy)
    ax.set_zlim(zs.min() - pad_z, zs.max() + pad_z)
    try:
        ax.set_box_aspect(
            (
                xs.max() - xs.min() + 2 * pad_xy,
                ys.max() - ys.min() + 2 * pad_xy,
                zs.max() - zs.min() + 2 * pad_z,
            )
        )
    except (AttributeError, TypeError):
        # Older matplotlib has no set_box_aspect on 3D; equal axis is the fallback.
        pass

    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_zlabel("Z (m)")
    ax.set_title(f"Bird's-eye view — {idf_path.name}")
    ax.view_init(elev=30, azim=-60)  # isometric

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_png, dpi=dpi)
    plt.close(fig)
    return out_png
