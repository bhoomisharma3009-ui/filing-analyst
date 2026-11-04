"""Rule-based screens for accounting and balance sheet red flags.

These are deliberately simple and transparent. A flag is a reason to read a section of
the filing more carefully, not a conclusion. Thresholds are in THRESHOLDS so they can be
tuned without touching the logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

THRESHOLDS = {
    "receivables_gap": 0.10,       # AR growth minus revenue growth
    "inventory_gap": 0.15,         # inventory growth minus revenue growth
    "inventory_materiality": 0.05, # ignore inventory under 5% of revenue
    "fcf_conversion": 0.60,        # FCF / net income
    "accruals_ratio": 0.10,
    "sbc_pct_revenue": 0.10,
    "margin_drop": 0.05,           # operating margin decline over two years
    "net_leverage": 3.0,
    "dilution": 0.03,
    "goodwill_pct_assets": 0.40,
}


@dataclass(frozen=True)
class Flag:
    code: str
    severity: str        # "high" | "medium" | "low"
    title: str
    evidence: str
    where_to_look: str


def _pct(x: float) -> str:
    return f"{x:.1%}"


def financial_flags(fin: pd.DataFrame, m: pd.DataFrame) -> list[Flag]:
    T = THRESHOLDS
    flags: list[Flag] = []
    year = str(fin.columns[-1].year)
    rev_g = m.loc["revenue_growth"].iloc[-1]

    ar_g = m.loc["receivables_growth"].iloc[-1]
    if pd.notna(ar_g) and pd.notna(rev_g) and ar_g - rev_g > T["receivables_gap"]:
        dso_now, dso_prev = m.loc["dso"].iloc[-1], m.loc["dso"].iloc[-2]
        flags.append(Flag(
            "receivables_outpacing_revenue", "medium", "Receivables growing faster than revenue",
            f"FY{year}: receivables {_pct(ar_g)} vs revenue {_pct(rev_g)}; DSO {dso_prev:.0f} -> {dso_now:.0f} days",
            "Revenue recognition policy, allowance for credit losses, customer concentration"))

    inv_g = m.loc["inventory_growth"].iloc[-1]
    inv_share = fin.loc["inventory"].iloc[-1] / fin.loc["revenue"].iloc[-1]
    if (pd.notna(inv_g) and pd.notna(rev_g) and inv_g - rev_g > T["inventory_gap"]
            and inv_share > T["inventory_materiality"]):
        flags.append(Flag(
            "inventory_build", "medium", "Inventory building ahead of sales",
            f"FY{year}: inventory {_pct(inv_g)} vs revenue {_pct(rev_g)}",
            "Inventory reserves, MD&A commentary on demand and supply commitments"))

    conv = m.loc["fcf_conversion"].iloc[-1]
    if pd.notna(conv) and conv < T["fcf_conversion"]:
        capex_share = m.loc["capex_pct_revenue"].iloc[-1]
        flags.append(Flag(
            "weak_cash_conversion", "medium" if conv > 0 else "high", "Free cash flow well below net income",
            f"FY{year}: FCF / net income = {conv:.2f}x (capex {_pct(capex_share)} of revenue)",
            "Cash flow statement, capex plans in MD&A, working capital"))

    acc = m.loc["accruals_ratio"].iloc[-1]
    if pd.notna(acc) and acc > T["accruals_ratio"]:
        flags.append(Flag(
            "high_accruals", "high", "Earnings running well ahead of operating cash flow",
            f"FY{year}: (net income - CFO) / average assets = {acc:.2f}",
            "Non-cash gains, capitalized costs, changes in working capital"))

    sbc = m.loc["sbc_pct_revenue"].iloc[-1]
    if pd.notna(sbc) and sbc > T["sbc_pct_revenue"]:
        flags.append(Flag(
            "sbc_heavy", "medium", "Stock-based compensation is a large expense",
            f"FY{year}: SBC = {_pct(sbc)} of revenue; adjusted metrics that exclude it overstate margins",
            "Equity compensation note, non-GAAP reconciliation"))

    om = m.loc["operating_margin"].dropna()
    if len(om) >= 3 and om.iloc[-3] - om.iloc[-1] > T["margin_drop"]:
        flags.append(Flag(
            "margin_compression", "medium", "Operating margin compression",
            f"Operating margin {_pct(om.iloc[-3])} -> {_pct(om.iloc[-1])} over two years",
            "MD&A segment results, pricing and cost commentary"))

    lev, lev_prev = m.loc["net_debt_to_ebitda"].iloc[-1], m.loc["net_debt_to_ebitda"].iloc[-2]
    ebitda = m.loc["ebitda"].iloc[-1]
    if pd.notna(lev) and lev > T["net_leverage"]:
        rising = pd.notna(lev_prev) and lev > lev_prev
        flags.append(Flag(
            "high_leverage", "high" if rising else "medium", "Elevated leverage",
            f"FY{year}: net debt / EBITDA {lev:.1f}x" + (f" (up from {lev_prev:.1f}x)" if rising else ""),
            "Debt note: maturities, covenants, rating triggers"))
    elif pd.notna(ebitda) and ebitda <= 0 and m.loc["net_debt"].iloc[-1] > 0:
        flags.append(Flag(
            "negative_ebitda_with_debt", "high", "Negative EBITDA with net debt outstanding",
            f"FY{year}: EBITDA {ebitda / 1e6:,.0f}m, net debt {m.loc['net_debt'].iloc[-1] / 1e6:,.0f}m",
            "Liquidity section of MD&A, debt maturities"))

    eq = fin.loc["equity"].iloc[-1]
    if pd.notna(eq) and eq < 0:
        flags.append(Flag(
            "negative_equity", "medium", "Negative shareholders' equity",
            f"FY{year}: stockholders' equity {eq / 1e6:,.0f}m",
            "Accumulated deficit vs buybacks; whether losses or capital returns drove it"))

    dil = m.loc["share_count_growth"].iloc[-1]
    if pd.notna(dil) and dil > T["dilution"]:
        flags.append(Flag(
            "dilution", "low", "Diluted share count rising",
            f"FY{year}: diluted shares {_pct(dil)} YoY",
            "Equity issuance, convertibles, SBC"))

    gw = m.loc["goodwill_pct_assets"].iloc[-1]
    if pd.notna(gw) and gw > T["goodwill_pct_assets"]:
        flags.append(Flag(
            "goodwill_heavy", "low", "Goodwill is a large share of assets",
            f"FY{year}: goodwill = {_pct(gw)} of total assets",
            "Impairment testing assumptions and reporting unit headroom"))

    g = m.loc["revenue_growth"].dropna()
    if len(g) >= 2 and g.iloc[-1] < 0 and g.iloc[-2] < 0:
        flags.append(Flag(
            "revenue_decline", "medium", "Revenue down two years running",
            f"Revenue growth {_pct(g.iloc[-2])}, then {_pct(g.iloc[-1])}",
            "Segment disclosure, market share commentary"))
    # Depreciation lag screen
    required_rows = {"d_and_a", "capex", "revenue"}

    if required_rows.issubset(fin.index):
        da = fin.loc["d_and_a"].iloc[-1]
        capex = fin.loc["capex"].iloc[-1]
        revenue = fin.loc["revenue"].iloc[-1]

        if (pd.notna(da) and pd.notna(capex) and pd.notna(revenue)
                and capex > 0 and revenue > 0):

            da_to_capex = da / capex
            capex_intensity = capex / revenue

            if capex_intensity > 0.25 and da_to_capex < 0.40:
                flags.append(Flag(
                    "depreciation_lag",
                    "medium",
                    "Potential depreciation lag from elevated capital expenditure",
                    f"FY{year}: D&A to CapEx = {da_to_capex:.2f}x; "
                    f"CapEx = {_pct(capex_intensity)} of revenue",
                    "PP&E note, useful-life assumptions, depreciation policy and future margin impact"
                ))
    return flags


_TEXT_SCREENS = [
    ("going_concern", "high", "Going concern language",
     r"substantial doubt (about|regarding) (the company's|our|its) ability to continue as a going concern",
     ["7", "8"], "Liquidity plans and auditor's report"),
    ("material_weakness", "high", "Material weakness in internal controls",
     r"(identified|identify|existence of) (a |an |two |three |several )?material weakness"
     r"|(controls?|control over financial reporting) (was|were) not effective",
     ["9A"], "Item 9A remediation plan and auditor attestation"),
    ("restatement", "high", "Restatement of previously issued financials",
     r"restate(d|ment of)? (our |the )?(previously issued|prior period)",
     ["7", "8", "9A"], "Restatement note and its impact on reported periods"),
]


def text_flags(items: dict[str, str]) -> list[Flag]:
    flags = []
    for code, sev, title, pattern, where, look in _TEXT_SCREENS:
        for item in where:
            text = items.get(item, "")
            m = re.search(pattern, text, re.I)
            if m:
                lo, hi = max(0, m.start() - 160), min(len(text), m.end() + 160)
                snippet = re.sub(r"\s+", " ", text[lo:hi]).strip()
                flags.append(Flag(code, sev, title, f'Item {item}: "...{snippet}..."', look))
                break
   
    return flags
