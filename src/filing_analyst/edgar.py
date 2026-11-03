"""Thin SEC EDGAR client with an on-disk cache.

The SEC asks automated clients to send a descriptive User-Agent with a contact address
and to stay under 10 requests per second. Set SEC_USER_AGENT, e.g.
    export SEC_USER_AGENT="Jane Doe jane@example.com"
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path

import requests

CACHE_DIR = Path(os.environ.get("FILING_ANALYST_CACHE", Path.home() / ".cache" / "filing-analyst"))
_MIN_INTERVAL = 0.15  # seconds between live requests (~6/s, under the SEC's 10/s limit)


@dataclass(frozen=True)
class Filing:
    cik: int
    ticker: str
    company: str
    form: str
    accession: str
    filing_date: str
    report_date: str
    primary_document: str

    @property
    def url(self) -> str:
        acc = self.accession.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{self.cik}/{acc}/{self.primary_document}"

    @property
    def fiscal_year(self) -> int:
        return int(self.report_date[:4])


class Edgar:
    def __init__(self, user_agent: str | None = None, cache_dir: Path = CACHE_DIR):
        self.user_agent = user_agent or os.environ.get("SEC_USER_AGENT")
        if not self.user_agent:
            raise RuntimeError(
                "Set SEC_USER_AGENT to a name and email, e.g. 'Jane Doe jane@example.com'. "
                "The SEC blocks requests without one."
            )
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"})
        self._last = 0.0

    # ---- transport ---------------------------------------------------------------------
    def _get(self, url: str, max_age_days: float | None = None) -> bytes:
        path = self.cache_dir / sha1(url.encode()).hexdigest()
        if path.exists():
            age_days = (time.time() - path.stat().st_mtime) / 86400
            if max_age_days is None or age_days < max_age_days:
                return path.read_bytes()
        wait = _MIN_INTERVAL - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        resp = self._session.get(url, timeout=30)
        self._last = time.monotonic()
        resp.raise_for_status()
        path.write_bytes(resp.content)
        return resp.content

    def _json(self, url: str, max_age_days: float | None = None) -> dict:
        return json.loads(self._get(url, max_age_days))

    # ---- lookups -----------------------------------------------------------------------
    def cik(self, ticker: str) -> tuple[int, str]:
        data = self._json("https://www.sec.gov/files/company_tickers.json", max_age_days=7)
        ticker = ticker.upper().replace(".", "-")
        for row in data.values():
            if row["ticker"].upper() == ticker:
                return int(row["cik_str"]), row["title"]
        raise KeyError(f"Ticker {ticker} not found in SEC company list")

    def filings(self, ticker: str, form: str = "10-K") -> list[Filing]:
        """Annual reports for a ticker, newest first. Amendments (10-K/A) are excluded."""
        cik, _ = self.cik(ticker)
        sub = self._json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", max_age_days=1)
        recent = sub["filings"]["recent"]
        out = []
        for i, f in enumerate(recent["form"]):
            if f != form:
                continue
            out.append(Filing(
                cik=cik, ticker=ticker.upper(), company=sub["name"], form=f,
                accession=recent["accessionNumber"][i], filing_date=recent["filingDate"][i],
                report_date=recent["reportDate"][i], primary_document=recent["primaryDocument"][i],
            ))
        return out

    def filing(self, ticker: str, fiscal_year: int | None = None) -> Filing:
        filings = self.filings(ticker)
        if not filings:
            raise LookupError(f"No 10-K filings found for {ticker}")
        if fiscal_year is None:
            return filings[0]
        for f in filings:
            if f.fiscal_year == fiscal_year:
                return f
        years = sorted({f.fiscal_year for f in filings})
        raise LookupError(f"No 10-K for fiscal {fiscal_year}; available: {years}")

    def document(self, filing: Filing) -> str:
        return self._get(filing.url).decode("utf-8", errors="replace")

    def company_facts(self, ticker: str) -> dict:
        cik, _ = self.cik(ticker)
        return self._json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", max_age_days=1)
