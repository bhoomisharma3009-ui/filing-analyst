"""Memo plumbing without calling the API: document assembly, request shape, citation rendering."""

from datetime import date
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from filing_analyst import memo
from filing_analyst.context import FilingContext
from filing_analyst.edgar import Filing
from filing_analyst.financials import metrics


@pytest.fixture
def ctx():
    years = [date(2023, 12, 31), date(2024, 12, 31)]
    fin = pd.DataFrame({"revenue": [100.0, 120.0], "net_income": [10.0, 12.0], "cfo": [12.0, 14.0],
                        "capex": [2.0, 3.0], "operating_income": [15.0, 18.0], "d_and_a": [1.0, 1.0],
                        "total_assets": [50.0, 60.0], "total_debt": [5.0, 5.0], "cash": [2.0, 3.0]},
                       index=years).T
    for row in ["gross_profit", "cost_of_revenue", "sbc", "interest_expense", "diluted_shares",
                "receivables", "inventory", "goodwill", "equity"]:
        fin.loc[row] = float("nan")
    filing = Filing(1, "TEST", "Test Corp", "10-K", "0000-00-000001", "2025-02-01", "2024-12-31", "t.htm")
    return FilingContext(filing, None, {"1A": "Risky.", "7": "y" * (memo.MAX_SECTION_CHARS + 10)},
                         fin, metrics(fin), [], None)


def test_documents_have_citations_and_truncation_is_reported(ctx):
    docs, truncated = memo.build_documents(ctx, ["1", "7", "1A"])
    titles = [d["title"] for d in docs]
    assert titles == ["Financial summary (XBRL)", "Accounting screens", "Risk factor changes vs prior year",
                      "Item 7. Management's Discussion and Analysis", "Item 1A. Risk Factors"]
    assert all(d["citations"] == {"enabled": True} for d in docs)
    assert truncated == ["7"]
    assert docs[3]["source"]["data"].endswith("[Section truncated by filing-analyst for length.]")


def test_request_shape(ctx, monkeypatch):
    captured = {}

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return NS(stop_reason="end_turn", model=memo.MODEL, content=[NS(type="text", text="Memo.", citations=None)],
                      usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                               cache_creation_input_tokens=0))

    class FakeClient:
        beta = NS(messages=NS(stream=lambda **kw: captured.update(kw) or FakeStream()))

    monkeypatch.setattr(memo, "_client", lambda: FakeClient())
    result = memo.write_memo(ctx)
    assert captured["model"] == "claude-opus-5-5"
    assert captured["thinking"] == {"type": "adaptive"}
    assert captured["fallbacks"] == "default"
    assert captured["betas"] == ["server-side-fallback-2026-07-01"]
    assert "Memo." in result.markdown and "Test Corp (TEST)" in result.markdown


def test_refusal_raises(ctx, monkeypatch):
    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return NS(stop_reason="refusal", content=[])

    monkeypatch.setattr(memo, "_client", lambda: NS(beta=NS(messages=NS(stream=lambda **kw: FakeStream()))))
    with pytest.raises(RuntimeError):
        memo.write_memo(ctx)


def test_citations_become_deduplicated_footnotes():
    cite = lambda title, text: NS(document_title=title, document_index=0, cited_text=text)
    content = [
        NS(type="thinking", thinking=""),
        NS(type="text", text="Revenue grew 20%", citations=[cite("Financial summary (XBRL)", "Revenue 100 120")]),
        NS(type="text", text=", driven by cloud", citations=[cite("Item 7. MD&A", "Cloud revenue increased")]),
        NS(type="text", text=". Again 20%", citations=[cite("Financial summary (XBRL)", "Revenue 100 120")]),
        NS(type="text", text=".", citations=None),
    ]
    out = memo.render_with_citations(content)
    assert out.startswith("Revenue grew 20%[^1], driven by cloud[^2]. Again 20%[^1].")
    assert '[^1]: Financial summary (XBRL): "Revenue 100 120"' in out
    assert out.count("[^1]:") == 1
