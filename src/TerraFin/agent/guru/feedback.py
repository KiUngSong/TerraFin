"""Persona-fit + narrative-quality feedback used by the worker loop.

These helpers inspect a candidate `GuruResearchMemo` (or its raw text
fragments) and decide whether the worker must be asked to retry the memo
to better match the persona's worldview and language. They also expose
shared text-normalization helpers used elsewhere in the package.
"""

import re
from typing import Any, Mapping

from .memo import (
    GuruResearchMemo,
    GuruRoutePlan,
    HOWARD_MARKS,
    STANLEY_DRUCKENMILLER,
    WARREN_BUFFETT,
)
from .personas import GuruPersona


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _flatten_view_context(view_context: Mapping[str, Any]) -> str:
    if not view_context.get("available"):
        return ""
    parts: list[str] = []

    def _walk(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            if value.strip():
                parts.append(value.strip())
            return
        if isinstance(value, Mapping):
            for item in value.values():
                _walk(item)
            return
        if isinstance(value, list):
            for item in value:
                _walk(item)
            return
        parts.append(str(value))

    _walk(
        {
            "route": view_context.get("route"),
            "pageType": view_context.get("pageType"),
            "title": view_context.get("title"),
            "summary": view_context.get("summary"),
            "selection": view_context.get("selection"),
            "entities": view_context.get("entities"),
        }
    )
    return " ".join(parts)


def _macro_chart_context(view_context: Mapping[str, Any]) -> bool:
    if not view_context.get("available"):
        return False
    if str(view_context.get("pageType") or "").strip().lower() != "chart":
        return False
    context_text = _normalize_text(_flatten_view_context(view_context))
    return _contains_any(context_text, ("dxy", "vix", "tnx", "rates", "yield", "macro"))


def _is_broad_market_request(text: str, *, view_context: Mapping[str, Any] | None) -> bool:
    broad_market_terms = (
        "current market",
        "market status",
        "market cycle",
        "overall market",
        "broad market",
        "stock market",
        "market environment",
        "market setup",
        "equity market",
        "market trade",
        "where are we in the cycle",
        "the cycle right now",
        "s&p 500",
        "nasdaq",
        "dow",
        "spy",
        "qqq",
        "dia",
        "vt",
        "index",
        "indices",
    )
    if _contains_any(text, broad_market_terms):
        return True
    if not view_context or not view_context.get("available"):
        return False
    page_type = str(view_context.get("pageType") or "").strip().lower()
    if page_type in {"market-insights", "chart"}:
        context_text = _normalize_text(_flatten_view_context(view_context))
        return _contains_any(context_text, broad_market_terms)
    return False


def _persona_fit_feedback(
    *,
    persona: GuruPersona,
    route_plan: GuruRoutePlan,
    memo: GuruResearchMemo,
    user_message: str | None = None,
) -> str | None:
    thesis = _normalize_text(memo.thesis)
    combined = _normalize_text(
        " ".join(
            [
                memo.thesis,
                *memo.key_evidence,
                *memo.risks,
                *memo.open_questions,
                *memo.citations,
            ]
        )
    )
    technical_terms = ("rsi", "bollinger", "macd", "upper band", "overbought")
    technical_hits = sum(1 for term in technical_terms if term in combined)
    signature_hits = sum(1 for term in persona.signature_concepts if term.lower() in combined)
    # Broad-market detection needs the raw question text -- legacy routes
    # stashed signal into `route_plan.matched_terms` / `route_plan.reason`,
    # but `consult_<persona>` tool calls leave both empty. Prefer the
    # user_message when supplied; fall back to the route-plan fields for
    # transcript-replay of legacy plans.
    broad_market_text = _normalize_text(
        user_message
        if user_message is not None
        else " ".join(route_plan.matched_terms) + " " + route_plan.reason
    )
    broad_market = _is_broad_market_request(
        broad_market_text,
        view_context=route_plan.view_context,
    ) or route_plan.route_type in {"explicit", "macro"}

    if broad_market and technical_hits >= 2 and signature_hits == 0:
        return (
            "The memo relies on shared technical-analysis language but does not surface this investor's signature concepts."
        )
    narrative_feedback = _narrative_quality_feedback([memo.thesis, *memo.key_evidence, *memo.risks])
    if narrative_feedback:
        return narrative_feedback
    question_feedback = _open_question_quality_feedback(memo.open_questions)
    if question_feedback:
        return question_feedback
    if persona.name == WARREN_BUFFETT:
        worldview_feedback = _worldview_sentence_feedback(
            thesis=thesis,
            combined=combined,
            primary_terms=("business", "businesses", "owner", "price", "valuation", "wonderful business"),
            secondary_terms=("margin of safety", "patience", "cash", "optionality"),
            failure_text="A Buffett memo should open from the perspective of a long-term business owner and price discipline, not just valuation math.",
        )
        if worldview_feedback:
            return worldview_feedback
        if broad_market and technical_hits >= 1 and technical_hits >= max(signature_hits, 1):
            return "A Buffett broad-market answer cannot lean on RSI, MACD, or short-term tape language as primary evidence."
        if broad_market and signature_hits == 0:
            return "A Buffett broad-market answer should sound patient, valuation-disciplined, and anchored in margin of safety or cash/optionality."
    if persona.name == HOWARD_MARKS:
        worldview_feedback = _worldview_sentence_feedback(
            thesis=thesis,
            combined=combined,
            primary_terms=("cycle", "pendulum", "psychology", "optimism", "fear", "euphoria"),
            secondary_terms=("risk premium", "paid enough for the risk", "second-level", "prepare"),
            failure_text="A Howard Marks memo should sound like cycle position, psychology, and risk compensation are the center of gravity.",
        )
        if worldview_feedback:
            return worldview_feedback
        if broad_market and signature_hits == 0:
            return "A Howard Marks answer should foreground cycle position, psychology, risk premium, or second-level thinking."
    if persona.name == STANLEY_DRUCKENMILLER:
        worldview_feedback = _worldview_sentence_feedback(
            thesis=thesis,
            combined=combined,
            primary_terms=("liquidity", "rates", "yield", "bond yields", "macro tradeoff"),
            secondary_terms=("earnings", "tape", "animal spirits", "individual stock", "edge"),
            failure_text="A Druckenmiller memo should open with the macro tradeoff between rates/liquidity and what earnings or the tape are saying.",
        )
        if worldview_feedback:
            return worldview_feedback
        if broad_market and memo.stance == "abstain":
            return "A Druckenmiller broad-market answer should usually weigh the macro tradeoff explicitly instead of defaulting to abstain."
        if broad_market and signature_hits == 0:
            return "A Druckenmiller answer should sound macro-driven, with liquidity, yields, growth, animal spirits, or stock-selection tradeoffs."
    return None


def _worldview_sentence_feedback(
    *,
    thesis: str,
    combined: str,
    primary_terms: tuple[str, ...],
    secondary_terms: tuple[str, ...],
    failure_text: str,
) -> str | None:
    if not any(term in thesis for term in primary_terms):
        return failure_text
    if not any(term in combined for term in secondary_terms):
        return failure_text
    return None


def _open_question_quality_feedback(open_questions: list[str]) -> str | None:
    allowed_starts = {
        "what",
        "which",
        "whether",
        "how",
        "why",
        "will",
        "would",
        "could",
        "can",
        "is",
        "are",
        "should",
        "do",
        "does",
        "to",
        "where",
        "when",
        "if",
    }
    for question in open_questions:
        normalized = _normalize_text(question)
        if not normalized:
            continue
        words = normalized.split()
        if len(words) > 30:
            return "The memo's open questions should stay plain and concrete rather than sprawling or fragmentary."
        if any(marker in question for marker in ("[[", "]]", "{{", "}}", "__", "]]>", "<![", "=>")):
            return "The memo's open questions should read like real investor follow-up questions, not fragments."
        if words[0] not in allowed_starts and len(words) <= 4:
            return "The memo's open questions should read like real investor follow-up questions, not fragments."
    return None


def _narrative_quality_feedback(texts: list[str]) -> str | None:
    severe_garble = re.compile(r"(\[\[|\]\]|\{\{|\}\}|__|[A-Za-z]+_[A-Za-z]+|[A-Za-z]{4,}\]\)|\)\][A-Za-z]{2,})")
    for text in texts:
        stripped = text.strip()
        if not stripped:
            continue
        if '\\"' in stripped or '".' in stripped or '."' in stripped:
            return "The memo contains garbled quoted fragments rather than clean investor prose."
        if severe_garble.search(stripped):
            return "The memo contains garbled fragments rather than clean investor prose."
        for raw_word in stripped.replace(",", " ").replace(";", " ").split():
            cleaned = raw_word.strip("?.!()[]{}:;\"'")
            if raw_word.count("-") >= 2 and len(cleaned) > 18:
                return "The memo contains garbled compound phrasing rather than clean investor prose."
    return None


def _displayable_open_questions(open_questions: list[str]) -> list[str]:
    if _open_question_quality_feedback(open_questions):
        return []
    allowed_caps = {"SPY", "QQQ", "DIA", "VT", "IWM", "M2", "CPI", "VIX", "DXY", "Fed", "Federal", "Reserve", "Treasury", "Apple", "Buffett", "Marks", "Druckenmiller"}
    displayable: list[str] = []
    for question in open_questions:
        stripped = question.strip()
        if not stripped.endswith("?"):
            continue
        bad_wording = False
        for raw_word in stripped.replace(",", " ").replace(";", " ").split():
            if "-" in raw_word and not any(ch.isdigit() for ch in raw_word):
                bad_wording = True
                break
            cleaned = raw_word.strip("?.!()[]{}:;\"'")
            if cleaned and cleaned[0].isupper() and cleaned not in allowed_caps and raw_word != stripped.split()[0]:
                bad_wording = True
                break
        if not bad_wording:
            displayable.append(question)
    return displayable


def _displayable_memo_points(
    *,
    persona: GuruPersona,
    items: list[str],
    point_type: str,
) -> list[str]:
    keyword_priority: dict[str, tuple[tuple[str, ...], ...]] = {
        WARREN_BUFFETT: (
            ("moat", "pricing power", "brand", "ecosystem", "cash", "owner", "management", "capital allocation"),
            ("margin of safety", "intrinsic value", "price", "valuation", "discount", "premium", "pe", "multiple"),
        ),
        HOWARD_MARKS: (
            ("cycle", "psychology", "sentiment", "optimism", "euphoria", "fear", "fomo", "pendulum"),
            ("risk premium", "paid enough for the risk", "valuation", "breadth", "second-level", "downside"),
        ),
        STANLEY_DRUCKENMILLER: (
            ("liquidity", "rates", "yield", "bond", "earnings", "tape", "momentum", "animal spirits"),
            ("breadth", "volatility", "macro", "risk-reward", "valuation", "tradeoff", "edge"),
        ),
    }
    tiers = keyword_priority.get(persona.name, ((),))
    scored: list[tuple[int, str]] = []
    fallback: list[str] = []
    for item in items:
        stripped = item.strip()
        if not stripped:
            continue
        if _narrative_quality_feedback([stripped]):
            continue
        if any(marker in stripped for marker in ("[[", "]]", "{{", "}}", "__", "....", "=>")):
            continue
        normalized = _normalize_text(stripped)
        words = normalized.split()
        if len(words) < 4:
            continue
        score = 0
        for index, tier in enumerate(tiers):
            if any(term in normalized for term in tier):
                score = max(score, len(tiers) - index)
        if point_type == "evidence" and score == 0 and persona.name == STANLEY_DRUCKENMILLER:
            if any(term in normalized for term in ("spy", "qqq", "s&p", "nasdaq")):
                score = 1
        if score > 0:
            scored.append((score, stripped))
        else:
            fallback.append(stripped)
    scored.sort(key=lambda item: (-item[0], items.index(item[1])))
    selected = [item for _, item in scored[:3]]
    if not selected:
        selected = fallback[:3]
    return selected
