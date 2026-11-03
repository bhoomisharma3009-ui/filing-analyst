from filing_analyst.riskdiff import diff_risk_factors

P1 = ("Our results depend on demand from a small number of large customers, and the loss of any of them "
      "could materially reduce revenue and profitability in the period in which it occurs.")
P2 = ("We rely on third-party manufacturers located primarily in Asia, and disruptions caused by natural "
      "disasters, trade restrictions or public health events could delay deliveries to our customers.")
P2_EDIT = P2.replace("primarily in Asia", "primarily in Taiwan and Vietnam")
P_NEW = ("We are investing heavily in AI infrastructure, and if demand for AI services does not develop as "
         "expected we may be left with underutilized data center capacity and impairment charges.")
P_OLD = ("Our pension obligations are underfunded and changes in discount rates or asset returns could "
         "require us to make significant additional contributions in future years.")


def test_diff_classifies_paragraphs():
    prior = "\n".join([P1, P2, P_OLD])
    current = "\n".join([P1, P2_EDIT, P_NEW])
    d = diff_risk_factors(current, prior)
    assert d.added == [P_NEW]
    assert d.removed == [P_OLD]
    assert d.unchanged + len(d.rewritten) == 2


def test_identical_sections():
    d = diff_risk_factors(P1 + "\n" + P2, P1 + "\n" + P2)
    assert (d.added, d.removed, d.rewritten, d.unchanged) == ([], [], [], 2)
