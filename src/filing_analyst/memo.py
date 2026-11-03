"""Claude-written screening memo and Q&A, with citations back to the filing.

Each input (financial summary, screens, risk factor diff, 10-K sections) is passed as a
separate plain-text document with citations enabled, so every factual sentence in the
output can point to the exact passage it came from. Citations are rendered as Markdown
footnotes.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from importlib import resources

import anthropic

from .context import FilingContext, financial_table, flags_text, risk_diff_text, section_title

MODEL = "claude-opus-5-5"
MAX_SECTION_CHARS = 400_000   # ~100k tokens; a few banks' MD&As exceed this
SECTIONS_FOR_MEMO = ["1", "7", "1A", "7A", "9A", "3"]
SECTIONS_FOR_QA = ["1", "1A", "1C", "3", "7", "7A", "8", "9A"]


@dataclass
class Result:
    markdown: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    truncated_sections: list[str]


def _document(title: str, text: str) -> dict:
    return {
        "type": "document",
        "source": {"type": "text", "media_type": "text/plain", "data": text},
        "title": title,
        "citations": {"enabled": True},
    }


def build_documents(ctx: FilingContext, sections: list[str]) -> tuple[list[dict], list[str]]:
    docs = [
        _document("Financial summary (XBRL)", financial_table(ctx)),
        _document("Accounting screens", flags_text(ctx)),
        _document("Risk factor changes vs prior year", risk_diff_text(ctx)),
    ]
    truncated = []
    for item in sections:
        text = ctx.items.get(item)
        if not text:
            continue
        if len(text) > MAX_SECTION_CHARS:
            truncated.append(item)
            text = text[:MAX_SECTION_CHARS] + "\n\n[Section truncated by filing-analyst for length.]"
        docs.append(_document(section_title(item), text))
    return docs, truncated


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _call(system: str, docs: list[dict], instruction: str, effort: str, max_tokens: int):
    client = _client()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": [*docs, {"type": "text", "text": instruction}]}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        # The filing documents are the large, stable prefix; caching makes follow-up
        # questions on the same filing much cheaper.
        cache_control={"type": "ephemeral"},
        # If a safety classifier declines, retry on Anthropic's recommended fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "refusal":
        raise RuntimeError("The model declined to answer this request.")
    if response.stop_reason == "max_tokens":
        print("warning: output hit max_tokens and may be cut off", file=sys.stderr)
    return response


def render_with_citations(content) -> str:
    """Turn text blocks with citations into Markdown with numbered footnotes."""
    body: list[str] = []
    notes: dict[tuple[str, str], int] = {}
    for block in content:
        if getattr(block, "type", None) != "text":
            continue
        body.append(block.text)
        marks = []
        for c in getattr(block, "citations", None) or []:
            key = (c.document_title or f"Document {c.document_index}", c.cited_text.strip())
            if key not in notes:
                notes[key] = len(notes) + 1
            marks.append(notes[key])
        if marks:
            body.append("".join(f"[^{n}]" for n in dict.fromkeys(marks)))
    text = "".join(body).strip()
    if notes:
        text += "\n\n---\n\n**Sources**\n\n"
        for (title, cited), n in notes.items():
            quote = " ".join(cited.split())
            if len(quote) > 300:
                quote = quote[:297] + "..."
            text += f'[^{n}]: {title}: "{quote}"\n'
    return text


def write_memo(ctx: FilingContext, effort: str = "high") -> Result:
    system = resources.files("filing_analyst.prompts").joinpath("memo_system.md").read_text()
    docs, truncated = build_documents(ctx, SECTIONS_FOR_MEMO)
    instruction = (
        f"Write the screening memo for {ctx.title}, filed {ctx.filing.filing_date}. "
        "Cite the documents for factual claims."
    )
    if truncated:
        instruction += f" Note: these sections were truncated for length: {', '.join(truncated)}."
    response = _call(system, docs, instruction, effort, max_tokens=32_000)

    header = (
        f"# {ctx.filing.company} ({ctx.filing.ticker}): FY{ctx.filing.fiscal_year} 10-K screening memo\n\n"
        f"*Filed {ctx.filing.filing_date} · [source filing]({ctx.filing.url}) · "
        f"drafted by {response.model} via filing-analyst on {date.today().isoformat()}. "
        "First-pass research notes, not investment advice.*\n\n"
    )
    usage = response.usage
    return Result(
        markdown=header + render_with_citations(response.content),
        model=response.model,
        input_tokens=usage.input_tokens + (usage.cache_read_input_tokens or 0)
        + (usage.cache_creation_input_tokens or 0),
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        truncated_sections=truncated,
    )


QA_SYSTEM = (
    "You answer questions about a company's 10-K for an investment analyst. Answer only from the "
    "documents provided and cite them. If the filing does not answer the question, say so plainly "
    "and say where you looked. Be concise and quantitative."
)


def ask(ctx: FilingContext, question: str, effort: str = "medium") -> Result:
    docs, truncated = build_documents(ctx, SECTIONS_FOR_QA)
    response = _call(QA_SYSTEM, docs, question, effort, max_tokens=16_000)
    usage = response.usage
    return Result(
        markdown=render_with_citations(response.content),
        model=response.model,
        input_tokens=usage.input_tokens + (usage.cache_read_input_tokens or 0)
        + (usage.cache_creation_input_tokens or 0),
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        truncated_sections=truncated,
    )
