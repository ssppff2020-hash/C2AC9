"""
SynthRule — answer parsing and scoring.

Scoring is exact-match on the symbol sequence, with an edit-distance partial
credit score as a secondary signal.  Two points of care:

* Symbols are units, not characters.  All comparison happens on token lists,
  so an answer of ``qazomv`` is correctly read as ``[qa, zo, mv]`` rather than
  as six characters.
* Parsing must not reward a model for hedging.  We take the *last* declared
  ``ANSWER:`` line, which is the convention we state in the prompt, and we
  never search the prose for something that happens to look right.

Author: Songpengfei
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

Seq = List[str]

_ANSWER_RE = re.compile(r"ANSWER\s*:\s*\[([^\]]*)\]", re.IGNORECASE)
_ANY_BRACKET_RE = re.compile(r"\[([^\]]*)\]")
_SPLIT_RE = re.compile(r"[,\s、，]+")
_STRIP_CHARS = "[]() \t\r\n\"'`."


def _tokenize_fallback(raw: str, symbols: Sequence[str]) -> List[str]:
    """Longest-match tokenizer for answers written without separators.

    Some models emit ``[qazomv]`` for the alphabet {qa, zo, mv}.  Splitting on
    whitespace yields one unknown token, so we retry by greedily consuming the
    longest known symbol at each position.  Symbols are at most two characters
    in every alphabet we ship, so this is cheap and unambiguous.
    """
    text = re.sub(r"[\s,\[\]()]", "", raw)
    if not text:
        return []
    by_len = sorted(set(symbols), key=len, reverse=True)
    out: List[str] = []
    i = 0
    while i < len(text):
        for sym in by_len:
            if text.startswith(sym, i):
                out.append(sym)
                i += len(sym)
                break
        else:
            return []  # a character we cannot attribute -> give up, score as wrong
    return out


def parse_answer(text: Optional[str], symbols: Sequence[str]) -> Optional[Seq]:
    """Extract the predicted symbol sequence, or None if nothing parses."""
    if not text:
        return None

    raw: Optional[str] = None
    matches = _ANSWER_RE.findall(text)
    if matches:
        raw = matches[-1]
    else:
        bracket = _ANY_BRACKET_RE.findall(text)
        if bracket:
            raw = bracket[-1]
        else:
            # No brackets at all: look at the final non-empty line.
            lines = [ln for ln in text.strip().splitlines() if ln.strip()]
            if lines:
                raw = lines[-1]

    if raw is None:
        return None

    cleaned = raw.strip().strip(_STRIP_CHARS)
    if not cleaned:
        # An explicitly empty bracket is a legitimate answer for universes
        # whose rules can delete every symbol -- treat it as the empty sequence.
        return []

    parts = [p.strip().strip(_STRIP_CHARS) for p in _SPLIT_RE.split(cleaned)]
    parts = [p for p in parts if p]
    symbol_set = set(symbols)
    if parts and all(p in symbol_set for p in parts):
        return parts

    fallback = _tokenize_fallback(cleaned, symbols)
    if fallback:
        return fallback
    return None


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------


def levenshtein(a: Sequence[str], b: Sequence[str]) -> int:
    """Standard edit distance over token lists."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(
                min(
                    prev[j] + 1,          # deletion
                    cur[j - 1] + 1,       # insertion
                    prev[j - 1] + (ca != cb),  # substitution
                )
            )
        prev = cur
    return prev[-1]


@dataclass
class Score:
    exact: int          # 1 or 0
    partial: float      # 1 - normalised edit distance, in [0, 1]
    parsed: bool
    predicted: Optional[Seq]


def score_answer(predicted: Optional[Seq], gold: Seq) -> Score:
    if predicted is None:
        return Score(exact=0, partial=0.0, parsed=False, predicted=None)
    if predicted == list(gold):
        return Score(exact=1, partial=1.0, parsed=True, predicted=predicted)
    denom = max(len(predicted), len(gold))
    if denom == 0:
        return Score(exact=1, partial=1.0, parsed=True, predicted=predicted)
    partial = 1.0 - levenshtein(predicted, list(gold)) / denom
    return Score(exact=0, partial=max(0.0, partial), parsed=True, predicted=predicted)


def format_answer(seq: Sequence[str]) -> str:
    return "[" + ", ".join(seq) + "]"
