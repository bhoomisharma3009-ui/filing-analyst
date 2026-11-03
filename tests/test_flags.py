from datetime import date

import numpy as np
import pandas as pd

from filing_analyst.financials import metrics
from filing_analyst.flags import financial_flags, text_flags

YEARS = [date(2022, 12, 31), date(2023, 12, 31), date(2024, 12, 31)]


def fin(**overrides):
    base = {
        "revenue": [100, 110, 121], "cost_of_revenue": [50, 55, 60], "gross_profit": [50, 55, 61],
        "operating_income": [20, 22, 24], "net_income": [15, 16, 17], "d_and_a": [5, 5, 5],
        "sbc": [2, 2, 2], "interest_expense": [1, 1, 1], "cfo": [20, 21, 22], "capex": [4, 4, 4],
        "diluted_shares": [100, 100, 100], "cash": [10, 10, 10], "receivables": [20, 22, 24],
        "inventory": [10, 11, 12], "total_assets": [200, 210, 220], "goodwill": [10, 10, 10],
        "equity": [100, 105, 110], "total_debt": [30, 30, 30],
    }
    base.update(overrides)
    return pd.DataFrame(base, index=YEARS, dtype=float).T


def codes(f):
    return {x.code for x in financial_flags(f, metrics(f))}


def test_clean_company_triggers_nothing():
    assert codes(fin()) == set()


def test_receivables_and_inventory():
    assert "receivables_outpacing_revenue" in codes(fin(receivables=[20, 22, 30]))
    assert "inventory_build" in codes(fin(inventory=[10, 11, 16]))
    # Inventory under 5% of revenue is ignored even if it jumps.
    assert "inventory_build" not in codes(fin(inventory=[1, 1, 3]))


def test_cash_conversion_and_accruals():
    f = fin(cfo=[20, 21, 6], net_income=[15, 16, 30])
    c = codes(f)
    assert "weak_cash_conversion" in c and "high_accruals" in c


def test_leverage_equity_dilution_decline():
    c = codes(fin(total_debt=[30, 60, 150], equity=[10, 5, -5], diluted_shares=[100, 100, 110],
                  revenue=[130, 120, 110], gross_profit=[60, 55, 50]))
    assert {"high_leverage", "negative_equity", "dilution", "revenue_decline"} <= c


def test_margin_compression():
    assert "margin_compression" in codes(fin(operating_income=[20, 15, 10]))


def test_negative_ebitda_with_debt():
    assert "negative_ebitda_with_debt" in codes(fin(operating_income=[20, 5, -20]))


def test_text_flags():
    items = {
        "9A": "Management identified a material weakness in internal control over financial reporting.",
        "8": "There is substantial doubt about the Company's ability to continue as a going concern.",
    }
    found = {f.code for f in text_flags(items)}
    assert found == {"material_weakness", "going_concern"}
    assert text_flags({"9A": "No material weakness was identified. Controls were effective."}) == []
