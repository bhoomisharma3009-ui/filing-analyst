import math

import pytest

from filing_analyst.financials import annual_financials, metrics


def _fact(val, end, filed, start=None, form="10-K"):
    d = {"val": val, "end": end, "filed": filed, "form": form, "fp": "FY"}
    if start:
        d["start"] = start
    return d


def make_facts():
    usd = lambda *rows: {"units": {"USD": list(rows)}}
    return {"facts": {"us-gaap": {
        # Company switched revenue tags between years.
        "SalesRevenueNet": usd(_fact(100.0, "2022-12-31", "2023-02-01", "2022-01-01")),
        "RevenueFromContractWithCustomerExcludingAssessedTax": usd(
            _fact(110.0, "2023-12-31", "2024-02-01", "2023-01-01"),
            _fact(130.0, "2024-12-31", "2025-02-01", "2024-01-01"),
            # A quarterly value and a 10-Q value that must be ignored.
            _fact(35.0, "2024-12-31", "2025-02-01", "2024-10-01"),
            _fact(999.0, "2024-06-30", "2024-08-01", "2023-07-01", form="10-Q"),
        ),
        "NetIncomeLoss": usd(
            _fact(10.0, "2022-12-31", "2023-02-01", "2022-01-01"),
            _fact(12.0, "2023-12-31", "2024-02-01", "2023-01-01"),
            _fact(11.0, "2023-12-31", "2025-02-01", "2023-01-01"),   # restated in next 10-K
            _fact(15.0, "2024-12-31", "2025-02-01", "2024-01-01"),
        ),
        "NetCashProvidedByUsedInOperatingActivities": usd(
            _fact(14.0, "2022-12-31", "2023-02-01", "2022-01-01"),
            _fact(15.0, "2023-12-31", "2024-02-01", "2023-01-01"),
            _fact(20.0, "2024-12-31", "2025-02-01", "2024-01-01"),
        ),
        "PaymentsToAcquirePropertyPlantAndEquipment": usd(
            _fact(4.0, "2022-12-31", "2023-02-01", "2022-01-01"),
            _fact(5.0, "2023-12-31", "2024-02-01", "2023-01-01"),
            _fact(6.0, "2024-12-31", "2025-02-01", "2024-01-01"),
        ),
        "Assets": usd(_fact(200.0, "2022-12-31", "2023-02-01"), _fact(210.0, "2023-12-31", "2024-02-01"),
                      _fact(230.0, "2024-12-30", "2025-02-01")),   # one day off the period end
        "LongTermDebtNoncurrent": usd(_fact(40.0, "2024-12-31", "2025-02-01")),
        "LongTermDebtCurrent": usd(_fact(5.0, "2024-12-31", "2025-02-01")),
        "CashAndCashEquivalentsAtCarryingValue": usd(_fact(8.0, "2024-12-31", "2025-02-01")),
    }}}


def test_tag_fallback_restatement_and_period_filtering():
    fin = annual_financials(make_facts())
    assert [c.year for c in fin.columns] == [2022, 2023, 2024]
    assert fin.loc["revenue"].tolist() == [100.0, 110.0, 130.0]
    assert fin.loc["net_income"].tolist() == [10.0, 11.0, 15.0]     # latest filing wins
    assert fin.loc["total_assets"].iloc[-1] == 230.0                # matched within tolerance
    assert fin.loc["total_debt"].iloc[-1] == 45.0                   # current + noncurrent


def test_metrics():
    fin = annual_financials(make_facts())
    m = metrics(fin)
    assert m.loc["revenue_growth"].iloc[-1] == pytest.approx((130 - 110) / 110)
    assert m.loc["free_cash_flow"].iloc[-1] == 14.0
    assert m.loc["fcf_conversion"].iloc[-1] == pytest.approx(14.0 / 15.0)
    assert math.isclose(m.loc["accruals_ratio"].iloc[-1], (15 - 20) / ((230 + 210) / 2))
