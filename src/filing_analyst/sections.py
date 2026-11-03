"""Split a 10-K into its Items.

10-Ks repeat Item headings in the table of contents, in running page headers ("Item 1A"
at the top of every page) and in cross-references. A heading only counts here if the
Item number is followed by that Item's expected title, or, for filers like Intel that
drop Item numbers from the body, if a short line is the title on its own. Among the
remaining candidates, each Item keeps the one that produces the longest section before
the next heading, so the table-of-contents entry always loses.
"""

from __future__ import annotations

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Items we return, with display names.
ITEMS = {
    "1": "Business",
    "1A": "Risk Factors",
    "1C": "Cybersecurity",
    "3": "Legal Proceedings",
    "7": "Management's Discussion and Analysis",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9A": "Controls and Procedures",
}

# Title patterns for every Item, including ones we don't return, so they act as boundaries.
_TITLES = {
    "1": r"business",
    "1A": r"risk factors",
    "1B": r"unresolved staff comments",
    "1C": r"cybersecurity",
    "2": r"properties",
    "3": r"legal proceedings",
    "4": r"mine safety",
    "5": r"market for (the )?registrant",
    "6": r"(\[?reserved\]?|selected (consolidated )?financial data)",
    "7": r"management'?s discussion and analysis",
    "7A": r"quantitative and qualitative disclosures? about market risk",
    "8": r"financial statements and supplementary data",
    "9": r"changes in and disagreements",
    "9A": r"controls and procedures",
    "9B": r"other information",
    "9C": r"disclosure regarding foreign",
    "10": r"directors,? executive officers",
    "11": r"executive compensation",
    "12": r"security ownership",
    "13": r"certain relationships",
    "14": r"principal account",
    "15": r"exhibits?,? (and )?financial statement schedules",
    "16": r"form 10-k summary",
}
# Bare titles that are too generic to trust without an Item number.
_NO_BARE_TITLE = {"1", "2", "4", "6", "9B", "11"}

_ITEM_LINE = re.compile(r"^item\s+(\d{1,2}[a-c]?)\s*[.:\-\u2014\u2013]?\s*(.*)$", re.I)
_PAGE_FURNITURE = re.compile(r"^(item \d{1,2}[a-c]?(, ?\d{1,2}[a-c]?)*|part [ivx]+|\d{1,3}|table of contents)$", re.I)


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    # Hidden inline-XBRL header blocks hold machine-readable facts, not prose.
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for b in soup.find_all(["p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"]):
        b.insert_after("\n")
    text = soup.get_text()
    text = text.replace("\xa0", " ").replace("\u200b", "").replace("\u2019", "'")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip(" .:-")


def _headings(lines: list[str]) -> list[tuple[int, str]]:
    """(line_index, item) for every line that looks like a real Item heading."""
    found = []
    for i, line in enumerate(lines):
        m = _ITEM_LINE.match(line)
        if m:
            item = m.group(1).upper()
            title = m.group(2) or (lines[i + 1] if i + 1 < len(lines) else "")
            pat = _TITLES.get(item)
            if pat and re.match(pat, _norm(title)):
                found.append((i, item))
            continue
        if len(line) > 110:
            continue
        n = _norm(line)
        for item, pat in _TITLES.items():
            if item not in _NO_BARE_TITLE and re.fullmatch(pat + r"[^a-z]*(of financial condition.*)?", n):
                found.append((i, item))
                break
    return found


def split_items(text: str) -> dict[str, str]:
    """Return {item_number: section_text} for the Items in ITEMS that could be located."""
    lines = [ln.strip() for ln in text.split("\n")]
    heads = _headings(lines)
    if not heads:
        return {}

    # offsets[i] = number of characters before line i
    offsets = [0]
    for ln in lines:
        offsets.append(offsets[-1] + len(ln) + 1)

    best: dict[str, tuple[int, int]] = {}
    for k, (i, item) in enumerate(heads):
        # Section runs to the next heading for a *different* Item.
        j = next((h for h, it in heads[k + 1:] if it != item), len(lines))
        size = offsets[j] - offsets[i]
        if item not in best or size > offsets[best[item][1]] - offsets[best[item][0]]:
            best[item] = (i, j)

    out = {}
    for item in ITEMS:
        if item not in best:
            continue
        i, j = best[item]
        body = [ln for ln in lines[i + 1:j] if ln and not _PAGE_FURNITURE.match(ln)]
        # Drop the title line when the heading put it on its own line.
        if body and re.match(_TITLES[item], _norm(body[0])):
            body = body[1:]
        section = "\n".join(body).strip()
        if len(section) > 500:
            out[item] = section
    return out


def risk_factor_paragraphs(section: str, min_chars: int = 120) -> list[str]:
    """Break Item 1A into paragraphs.

    Short lines (sub-headings) are merged into the paragraph below. A line that does not
    end in sentence punctuation is joined to the next one, which repairs paragraphs split
    across a page break. Running "Risk Factors" headers are dropped.
    """
    lines = [ln.strip() for ln in section.split("\n")]
    lines = [ln for ln in lines if ln and _norm(ln) != "risk factors"]

    joined: list[str] = []
    for line in lines:
        if joined and (not re.search(r"[.!?:;\"')\]]$", joined[-1]) and len(joined[-1]) >= min_chars
                       or line[:1].islower()):
            joined[-1] = f"{joined[-1]} {line}"
        else:
            joined.append(line)

    paras, pending = [], ""
    for line in joined:
        if len(line) < min_chars:
            pending = f"{pending} {line}".strip()
            continue
        paras.append(f"{pending} {line}".strip() if pending else line)
        pending = ""
    return paras
