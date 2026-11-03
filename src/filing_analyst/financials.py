"""Standardized annual financials from SEC XBRL company facts.

Companies tag the same concept differently (Revenues vs RevenueFromContractWith...),
and switch tags over time, so each line item has an ordered list of tags. For each
fiscal year we take the first tag in the list that has a value. When the same period is
reported in several filings (the prior-year column of a later 10-K, or a restatement),
the most recently filed value wins.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

# (line item, [us-gaap tags in priority order], is_duration)
LINE_ITEMS: list[tuple[str, list[str], bool]] = [
    ("revenue", ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                 "RevenueFromContractWithCustomerIncludingAssessedTax", "RevenuesNetOfInterestExpense"], True),
    ("cost_of_revenue", ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"], True),
    ("gross_profit", ["GrossProfit"], True),
    ("operating_income", ["OperatingIncomeLoss"], True),
    ("net_income", ["NetIncomeLoss", "ProfitLoss"], True),
    ("d_and_a", ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
                 "DepreciationAndAmortization", "Depreciation"], True),
    ("sbc", ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"], True),
    ("interest_expense", ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt",
                          "InterestAndDebtExpense"], True),
    ("cfo", ["NetCashProvidedByUsedInOperatingActivities"], True),
    ("capex", ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"], True),
    ("diluted_shares", ["WeightedAverageNumberOfDilutedSharesOutstanding"], True),
    ("cash", ["CashAndCashEquivalentsAtCarryingValue",
              "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"], False),
    ("receivables", ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"], False),
    ("inventory", ["InventoryNet", "InventoryNetOfAllowancesCustomerAdvancesAndProgressBillings"], False),
    ("total_assets", ["Assets"], False),
    ("goodwill", ["Goodwill"], False),
    ("long_term_debt", ["LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"], False),
    ("long_term_debt_noncurrent", ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligationsNoncurrent"], False),
    ("long_term_debt_current", ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"], False),
    ("short_term_debt", ["CommercialPaper", "ShortTermBorrowings"], False),
    ("equity", ["StockholdersEquity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], False),
]


def _annual_series(facts: dict, tag: str, duration: bool) -> pd.Series:
    concept = facts.get("facts", {}).get("us-gaap", {}).get(tag)
    if not concept:
        return pd.Series(dtype=float)
    units = concept["units"].get("USD") or concept["units"].get("shares") or []
    rows = []
    for u in units:
        if not str(u.get("form", "")).startswith("10-K"):
            continue
        end = date.fromisoformat(u["end"])
        if duration:
            if "start" not in u:
                continue
            days = (end - date.fromisoformat(u["start"])).days
            if not 350 <= days <= 380:
                continue
        rows.append((end, u["filed"], float(u["val"])))
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows, columns=["end", "filed", "val"]).sort_values(["end", "filed"])
    s = df.groupby("end")["val"].last()
    s.index = pd.to_datetime(s.index)
    return s


def annual_financials(facts: dict, years: int = 6) -> pd.DataFrame:
    """Rows = line items, columns = fiscal year-end dates (oldest to newest), values in $."""
    raw = {}
    for name, tags, duration in LINE_ITEMS:
        merged = pd.Series(dtype=float)
        for tag in tags:
            s = _annual_series(facts, tag, duration)
            merged = s if merged.empty else merged.combine_first(s)
        raw[name] = merged

    # Fiscal year-ends are defined by the revenue (or net income) series.
    anchor = raw["revenue"] if not raw["revenue"].empty else raw["net_income"]
    if anchor.empty:
        raise ValueError("No annual revenue or net income found in XBRL facts")
    ends = sorted(anchor.index)[-years:]

    def align(s: pd.Series) -> pd.Series:
        # Balance sheet dates can differ by a day or two from the period end in some filings.
        out = {}
        for e in ends:
            if s.empty:
                out[e] = np.nan
                continue
            gap = np.abs((s.index - e).days)
            i = int(np.argmin(gap))
            out[e] = s.iloc[i] if gap[i] <= 7 else np.nan
        return pd.Series(out)

    df = pd.DataFrame({k: align(v) for k, v in raw.items()}).T
    df.columns = [c.date() for c in df.columns]

    if df.loc["gross_profit"].isna().all() and not df.loc["cost_of_revenue"].isna().all():
        df.loc["gross_profit"] = df.loc["revenue"] - df.loc["cost_of_revenue"]
    split = df.loc["long_term_debt_noncurrent"].fillna(0) + df.loc["long_term_debt_current"].fillna(0)
    total_ltd = df.loc["long_term_debt"].where(df.loc["long_term_debt"].notna(), split.replace(0, np.nan))
    df.loc["total_debt"] = total_ltd.fillna(0) + df.loc["short_term_debt"].fillna(0)
    return df.drop(index=["long_term_debt", "long_term_debt_noncurrent", "long_term_debt_current",
                          "short_term_debt"])


def metrics(fin: pd.DataFrame) -> pd.DataFrame:
    """Ratios used by the screens and the memo. Columns match `fin`."""
    f = fin
    rev = f.loc["revenue"]
    ebitda = f.loc["operating_income"] + f.loc["d_and_a"].fillna(0)
    fcf = f.loc["cfo"] - f.loc["capex"].fillna(0)
    avg_assets = (f.loc["total_assets"] + f.loc["total_assets"].shift(1, axis=0)) / 2
    avg_assets = avg_assets.fillna(f.loc["total_assets"])
    with np.errstate(divide="ignore", invalid="ignore"):
        m = pd.DataFrame({
            "revenue_growth": rev.pct_change(fill_method=None),
            "gross_margin": f.loc["gross_profit"] / rev,
            "operating_margin": f.loc["operating_income"] / rev,
            "net_margin": f.loc["net_income"] / rev,
            "ebitda": ebitda,
            "free_cash_flow": fcf,
            "fcf_margin": fcf / rev,
            "fcf_conversion": fcf / f.loc["net_income"].where(f.loc["net_income"] > 0),
            "sbc_pct_revenue": f.loc["sbc"] / rev,
            "dso": f.loc["receivables"] / rev * 365,
            "dio": f.loc["inventory"] / f.loc["cost_of_revenue"] * 365,
            "receivables_growth": f.loc["receivables"].pct_change(fill_method=None),
            "inventory_growth": f.loc["inventory"].pct_change(fill_method=None),
            "net_debt": f.loc["total_debt"] - f.loc["cash"].fillna(0),
            "net_debt_to_ebitda": (f.loc["total_debt"] - f.loc["cash"].fillna(0)) / ebitda.where(ebitda > 0),
            "interest_coverage": f.loc["operating_income"] / f.loc["interest_expense"].where(f.loc["interest_expense"] > 0),
            "accruals_ratio": (f.loc["net_income"] - f.loc["cfo"]) / avg_assets,
            "goodwill_pct_assets": f.loc["goodwill"] / f.loc["total_assets"],
            "share_count_growth": f.loc["diluted_shares"].pct_change(fill_method=None),
            "capex_pct_revenue": f.loc["capex"] / rev,
        }).T
    m.columns = f.columns
    return m
