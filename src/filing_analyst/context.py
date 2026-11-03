"""Everything we know about one 10-K before any model is involved."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .edgar import Edgar, Filing
from .financials import annual_financials, metrics
from .flags import Flag, financial_flags, text_flags
from .riskdiff import RiskDiff, diff_risk_factors
from .sections import ITEMS, html_to_text, split_items


@dataclass
class FilingContext:
    filing: Filing
    prior: Filing | None
    items: dict[str, str]
    financials: pd.DataFrame
    metrics: pd.DataFrame
    flags: list[Flag]
    risk_diff: RiskDiff | None

    @property
    def title(self) -> str:
        return f"{self.filing.company} ({self.filing.ticker}) FY{self.filing.fiscal_year} 10-K"


def load(ticker: str, fiscal_year: int | None = None, edgar: Edgar | None = None) -> FilingContext:
    edgar = edgar or Edgar()
    filing = edgar.filing(ticker, fiscal_year)
    items = split_items(html_to_text(edgar.document(filing)))

    older = [f for f in edgar.filings(ticker) if f.report_date < filing.report_date]
    prior = older[0] if older else None
    risk_diff = None
    if prior is not None and "1A" in items:
        prior_items = split_items(html_to_text(edgar.document(prior)))
        if "1A" in prior_items:
            risk_diff = diff_risk_factors(items["1A"], prior_items["1A"])

    fin = annual_financials(edgar.company_facts(ticker))
    # Only keep years up to and including the filing being analyzed.
    fin = fin.loc[:, [c for c in fin.columns if c <= pd.Timestamp(filing.report_date).date()]]
    m = metrics(fin)
    flags = financial_flags(fin, m) + text_flags(items)
    return FilingContext(filing, prior, items, fin, m, flags, risk_diff)


# ---- plain-text renderings used both in prompts and in CLI output ----------------------

_MONEY_ROWS = [
    ("Revenue", "revenue"), ("Gross profit", "gross_profit"), ("Operating income", "operating_income"),
    ("Net income", "net_income"), ("D&A", "d_and_a"), ("Stock-based compensation", "sbc"),
    ("Cash from operations", "cfo"), ("Capex", "capex"), ("Cash", "cash"), ("Total debt", "total_debt"),
    ("Receivables", "receivables"), ("Inventory", "inventory"), ("Goodwill", "goodwill"),
    ("Total assets", "total_assets"), ("Shareholders' equity", "equity"),
]
_RATIO_ROWS = [
    ("Revenue growth", "revenue_growth", "pct"), ("Gross margin", "gross_margin", "pct"),
    ("Operating margin", "operating_margin", "pct"), ("Free cash flow", "free_cash_flow", "money"),
    ("FCF margin", "fcf_margin", "pct"), ("FCF / net income", "fcf_conversion", "x"),
    ("Capex / revenue", "capex_pct_revenue", "pct"), ("SBC / revenue", "sbc_pct_revenue", "pct"),
    ("DSO (days)", "dso", "days"), ("Net debt / EBITDA", "net_debt_to_ebitda", "x"),
    ("Diluted share count growth", "share_count_growth", "pct"),
]


def _scale(fin: pd.DataFrame) -> tuple[float, str]:
    rev = fin.loc["revenue"].abs().max()
    return (1e9, "$bn") if rev >= 1e10 else (1e6, "$mm")


def _fmt(v: float, kind: str, div: float) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    if kind == "pct":
        return f"{v:.1%}"
    if kind == "x":
        return f"{v:.2f}x"
    if kind == "days":
        return f"{v:.0f}"
    x = v / div
    return f"({abs(x):,.1f})" if x < 0 else f"{x:,.1f}"


def financial_table(ctx: FilingContext) -> str:
    fin, m = ctx.financials, ctx.metrics
    div, unit = _scale(fin)
    years = [f"FY{c.year}" for c in fin.columns]
    width = 28
    lines = [f"{'(' + unit + ', fiscal years)':<{width}}" + "".join(f"{y:>10}" for y in years)]
    for label, key in _MONEY_ROWS:
        if key in fin.index and fin.loc[key].notna().any():
            lines.append(f"{label:<{width}}" + "".join(f"{_fmt(v, 'money', div):>10}" for v in fin.loc[key]))
    lines.append("")
    for label, key, kind in _RATIO_ROWS:
        if m.loc[key].notna().any():
            lines.append(f"{label:<{width}}" + "".join(f"{_fmt(v, kind, div):>10}" for v in m.loc[key]))
    return "\n".join(lines)


def flags_text(ctx: FilingContext) -> str:
    if not ctx.flags:
        return "No screens triggered."
    return "\n".join(f"[{f.severity.upper()}] {f.title}. {f.evidence}. Where to look: {f.where_to_look}."
                     for f in ctx.flags)


def risk_diff_text(ctx: FilingContext, max_each: int = 25) -> str:
    d = ctx.risk_diff
    if d is None:
        return "Prior-year risk factors unavailable."
    parts = [f"Compared with the FY{ctx.prior.fiscal_year} 10-K: {d.summary}.", "", "NEW THIS YEAR:"]
    parts += [f"- {p}" for p in d.added[:max_each]] or ["- none"]
    parts += ["", "REMOVED SINCE LAST YEAR:"]
    parts += [f"- {p}" for p in d.removed[:max_each]] or ["- none"]
    parts += ["", "SUBSTANTIALLY REWRITTEN (new wording):"]
    parts += [f"- {new}" for new, _, _ in d.rewritten[:max_each]] or ["- none"]
    return "\n".join(parts)


def section_title(item: str) -> str:
    return f"Item {item}. {ITEMS[item]}"
