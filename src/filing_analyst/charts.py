"""One-page financial overview chart."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .context import FilingContext, _scale  # noqa: E402

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK_2, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def _style(ax, title: str, subtitle: str) -> None:
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_2, length=0, labelsize=8.5)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold", pad=20)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=8.5, color=INK_2)


def overview(ctx: FilingContext, path: str | Path) -> Path:
    fin, m = ctx.financials, ctx.metrics
    div, unit = _scale(fin)
    years = [f"FY{c.year % 100:02d}" for c in fin.columns]
    x = np.arange(len(years))

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.9), dpi=200)

    ax = axes[0]
    rev = fin.loc["revenue"].values / div
    ax.bar(x, rev, color=BLUE, width=0.62)
    for xi, v in zip(x, rev):
        ax.text(xi, v * 1.01, f"{v:,.0f}" if v >= 100 else f"{v:,.1f}", ha="center", va="bottom",
                fontsize=8, color=INK)
    ax.set_xticks(x, years)
    _style(ax, "Revenue", unit)

    ax = axes[1]
    for key, label, color in [("gross_margin", "Gross", BLUE), ("operating_margin", "Operating", ORANGE),
                              ("fcf_margin", "Free cash flow", AQUA)]:
        vals = m.loc[key].values.astype(float) * 100
        if np.all(np.isnan(vals)):
            continue
        ax.plot(x, vals, color=color, linewidth=2, marker="o", markersize=5,
                markeredgecolor="white", markeredgewidth=1.2, label=label)
        last = np.where(~np.isnan(vals))[0][-1]
        ax.text(x[last] + 0.15, vals[last], f"{vals[last]:.0f}%", va="center", fontsize=8, color=INK)
    ax.axhline(0, color=INK_2, linewidth=0.8)
    ax.set_xticks(x, years)
    ax.set_xlim(-0.4, len(x) - 0.3)
    ax.legend(frameon=False, fontsize=8, loc="best")
    _style(ax, "Margins", "% of revenue")

    ax = axes[2]
    ni = fin.loc["net_income"].values / div
    fcf = m.loc["free_cash_flow"].values / div
    w = 0.36
    ax.bar(x - w / 2 - 0.01, ni, width=w, color=BLUE, label="Net income")
    ax.bar(x + w / 2 + 0.01, fcf, width=w, color=ORANGE, label="Free cash flow")
    ax.axhline(0, color=INK_2, linewidth=0.8)
    ax.set_xticks(x, years)
    ax.legend(frameon=False, fontsize=8, loc="best")
    _style(ax, "Earnings vs cash", unit)

    fig.suptitle(ctx.title, x=0.01, ha="left", fontsize=12.5, fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return Path(path)
