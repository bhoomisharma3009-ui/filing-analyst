"""filing-analyst command line.

    filing-analyst screen MSFT            financials, screens, risk factor changes (no API key needed)
    filing-analyst riskdiff MSFT          full text of new / removed risk factors
    filing-analyst memo MSFT --out memos  Claude-written screening memo with citations
    filing-analyst ask MSFT "How much of revenue is Azure?"
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

from . import charts
from .context import financial_table, load


def _print_screen(ctx) -> None:
    print(ctx.title)
    print(f"Filed {ctx.filing.filing_date}  {ctx.filing.url}")
    print(f"Sections found: {', '.join('Item ' + k for k in ctx.items)}\n")
    print(financial_table(ctx))
    print("\nScreens")
    if not ctx.flags:
        print("  none triggered")
    for f in ctx.flags:
        print(f"  [{f.severity:<6}] {f.title}")
        print(textwrap.fill(f.evidence, 96, initial_indent="           ", subsequent_indent="           "))
    if ctx.risk_diff:
        print(f"\nRisk factors vs FY{ctx.prior.fiscal_year}: {ctx.risk_diff.summary}")
        for p in ctx.risk_diff.added[:5]:
            print(textwrap.shorten(f"  + {p}", 110))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="filing-analyst", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("ticker")
        p.add_argument("--year", type=int, help="Fiscal year of the 10-K (default: latest)")
        return p

    p_screen = add("screen", "Financial summary, screens and risk factor changes")
    p_screen.add_argument("--chart", type=Path, help="Write an overview PNG here")
    add("riskdiff", "Print new and removed risk factors in full")
    p_memo = add("memo", "Write a screening memo with Claude")
    p_memo.add_argument("--out", type=Path, default=Path("memos"))
    p_memo.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    p_ask = add("ask", "Ask a question about the filing")
    p_ask.add_argument("question")
    args = parser.parse_args(argv)

    ctx = load(args.ticker, args.year)

    if args.cmd == "screen":
        _print_screen(ctx)
        if args.chart:
            args.chart.parent.mkdir(parents=True, exist_ok=True)
            charts.overview(ctx, args.chart)
            print(f"\nChart written to {args.chart}")

    elif args.cmd == "riskdiff":
        d = ctx.risk_diff
        if d is None:
            sys.exit("Prior-year risk factors not available")
        print(f"{ctx.title} vs FY{ctx.prior.fiscal_year}: {d.summary}\n")
        for label, paras in [("NEW", d.added), ("REMOVED", d.removed)]:
            print(f"==== {label} ({len(paras)}) ====\n")
            for p in paras:
                print(textwrap.fill(p, 100) + "\n")

    elif args.cmd in ("memo", "ask"):
        from . import memo  # imported lazily so `screen` works without the anthropic package configured

        if args.cmd == "memo":
            print(f"Drafting memo for {ctx.title} ...", file=sys.stderr)
            result = memo.write_memo(ctx, effort=args.effort)
            args.out.mkdir(parents=True, exist_ok=True)
            path = args.out / f"{ctx.filing.ticker}_FY{ctx.filing.fiscal_year}.md"
            path.write_text(result.markdown)
            print(f"Memo written to {path}")
        else:
            result = memo.ask(ctx, args.question)
            print(result.markdown)
        print(f"[{result.model}: {result.input_tokens:,} input tokens "
              f"({result.cache_read_tokens:,} cached), {result.output_tokens:,} output]", file=sys.stderr)


if __name__ == "__main__":
    main()
