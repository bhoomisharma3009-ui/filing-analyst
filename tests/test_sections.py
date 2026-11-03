from filing_analyst.sections import html_to_text, risk_factor_paragraphs, split_items

BODY = "x" * 600

FAKE_10K = f"""
Table of Contents
Item 1.
Business
3
Item 1A.
Risk Factors
9
Item 7.
Management's Discussion and Analysis of Financial Condition and Results of Operations
40
Item 8.
Financial Statements and Supplementary Data
60
PART I
ITEM 1. BUSINESS
We make widgets. {BODY}
Item 1
More about widgets, see Item 7 of this report. {BODY}
ITEM 1A. RISK FACTORS
Demand for widgets is cyclical. {BODY}
Item 1A
12
Competition could hurt margins. {BODY}
ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS
Revenue grew 12%. {BODY}
ITEM 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA
Balance sheet follows. {BODY}
"""


def test_split_items_skips_toc_and_page_headers():
    items = split_items(FAKE_10K)
    assert set(items) == {"1", "1A", "7", "8"}
    assert items["1A"].startswith("Demand for widgets")
    assert "Competition could hurt margins" in items["1A"]
    # Running header and page number are stripped, and the next Item is not included.
    assert "\nItem 1A\n" not in items["1A"]
    assert "Revenue grew" not in items["1A"]
    assert items["7"].startswith("Revenue grew 12%")


def test_bare_title_fallback():
    text = f"Risk Factors\nOur fabs are expensive. {BODY}\nManagement's Discussion and Analysis\nSales fell. {BODY}"
    items = split_items(text)
    assert items["1A"].startswith("Our fabs")
    assert items["7"].startswith("Sales fell")


def test_html_to_text_drops_hidden_xbrl():
    html = ('<html><body><div style="display:none"><ix:header>dei facts</ix:header></div>'
            "<p>Item&nbsp;1A.</p><p>Risk Factors</p><p>Real text</p></body></html>")
    text = html_to_text(html)
    assert "dei facts" not in text
    assert "Item 1A." in text and "Real text" in text


def test_paragraphs_repair_page_breaks_and_merge_headings():
    long_a = "Our supply chain depends on a small number of suppliers for critical components and any " \
             "disruption to those suppliers could delay shipments and"
    section = "\n".join([
        "Supply chain",
        long_a,
        "Risk Factors",
        "materially reduce revenue in the affected quarter.",
        "We face intense competition from larger companies with more resources, which could reduce our "
        "market share and pressure our pricing over time.",
    ])
    paras = risk_factor_paragraphs(section)
    assert len(paras) == 2
    assert paras[0].startswith("Supply chain Our supply chain")
    assert paras[0].endswith("affected quarter.")
