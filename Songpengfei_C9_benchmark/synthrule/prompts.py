"""
SynthRule — prompt construction for the four protocol phases.

A deliberate choice runs through all of this: the *rule grammar* is always
disclosed, but the *specific rules and their order* never are (except in
Phase D, which exists precisely to expose them as a control).

Disclosing the grammar keeps the task well-posed.  Without it the model would
be searching an unbounded hypothesis space, and a low score would be
uninformative -- it could not tell us whether the model failed to learn or
failed to guess the experimenter's ontology.  With the grammar fixed, the only
thing the model can get wrong is the induction itself.

Phases
------
A  prior-only baseline   no examples at all           -> floor / guess level
B  induction             k solved examples            -> learning gain
C  feedback learning     running feedback transcript  -> KSTAR dR -> K update
D  explicit-rule control rules stated in English      -> execution ceiling

Author: Songpengfei
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .generator import Task
from .universe import Rule

Seq = List[str]
Pair = Tuple[Seq, Seq]

ANSWER_INSTRUCTION = (
    "End your reply with exactly one line in this format:\n"
    "ANSWER: [sym1, sym2, ...]\n"
    "Use only the puzzle's own symbols. Do not explain the line."
)

SYSTEM_PROMPT = """\
You are solving a symbol-rewriting puzzle.

A hidden system rewrites sequences of symbols. The system applies a fix\
ed, ordered list of rules. Each rule is exactly one of these seven kinds:

  1. Replace every X with Y.
  2. Replace every X with two copies of itself (X becomes XX).
  3. Delete every X from the sequence.
  4. Reverse the entire sequence.
  5. If the sequence contains X, reverse the entire sequence; otherwise
     leave the sequence unchanged.
  6. If the sequence has more than N symbols, move the first symbol to the
     end; otherwise leave the sequence unchanged.
  7. Swap every X with Y, and every Y with X.

Rules are applied in the given order, each exactly once. A rule that does not
match leaves the sequence unchanged.

Sequences are written as [sym1, sym2, ...]. Each symbol is an indivisible
unit -- never split a multi-character symbol into its letters.

""" + ANSWER_INSTRUCTION


@dataclass
class Prompt:
    system: str
    user: str

    def as_messages(self) -> List[Dict[str, str]]:
        return [
            {"role": "user", "content": self.user},
        ]


def fmt_seq(seq: Sequence[str]) -> str:
    return "[" + ", ".join(seq) + "]"


def _symbol_header(task: Task) -> str:
    return "Puzzle symbols: " + ", ".join(task.universe.symbols)


def _support_block(support: Sequence[Pair], label: str = "Solved examples for THIS puzzle") -> str:
    lines = [f"{label}:"]
    for inp, out in support:
        lines.append(f"  {fmt_seq(inp)}  ->  {fmt_seq(out)}")
    return "\n".join(lines)


def _question_block(index: int, total: int, inp: Seq) -> str:
    return (
        f"Question {index} of {total}:\n"
        f"  Input: {fmt_seq(inp)}\n"
        f"  Output: ?"
    )


def _join(*blocks: str) -> str:
    return "\n\n".join(b for b in blocks if b)


# --------------------------------------------------------------------------
# Phase A -- prior-only baseline
# --------------------------------------------------------------------------


def build_phase_a(task: Task, index: int, total: int, inp: Seq) -> Prompt:
    """No examples. Measures what the model can do from prior knowledge alone.

    This is the floor. A model that genuinely cannot know the answer should
    land near chance here; a model that lands far *above* chance is telling us
    something surprising about short-sequence priors, and that is worth
    knowing before we interpret any learning gain.
    """
    user = _join(
        _symbol_header(task),
        "You are NOT given any solved examples for this puzzle. "
        "Reason from what you know about how such rule systems usually behave.",
        _question_block(index, total, inp),
        ANSWER_INSTRUCTION,
    )
    return Prompt(system=SYSTEM_PROMPT, user=user)


# --------------------------------------------------------------------------
# Phase B -- induction from examples
# --------------------------------------------------------------------------


def build_phase_b(task: Task, index: int, total: int, inp: Seq) -> Prompt:
    """k solved examples, then a held-out query. The core learning measurement."""
    user = _join(
        _symbol_header(task),
        _support_block(task.support),
        "Infer the hidden rules from those examples and apply them to the "
        "question below.",
        _question_block(index, total, inp),
        ANSWER_INSTRUCTION,
    )
    return Prompt(system=SYSTEM_PROMPT, user=user)


# --------------------------------------------------------------------------
# Phase C -- learning from feedback (KSTAR dR -> K)
# --------------------------------------------------------------------------

HistoryEntry = Tuple[Seq, Optional[str], Seq]  # (input, model's answer, correct output)


def build_phase_c(
    task: Task,
    index: int,
    total: int,
    inp: Seq,
    history: Sequence[HistoryEntry],
) -> Prompt:
    """Same evidence as Phase B, plus the model's own prior attempts and their
    corrections.

    This is the KSTAR loop made literal. The model acts (A), is shown the true
    result (R), and the discrepancy (dR) is the only new information it gets.
    If accuracy on later items does not exceed the first items, the model is
    not updating K from dR -- it is merely restating its initial guess.

    The transcript is passed explicitly rather than relying on server-side
    conversation state, so the whole protocol stays reproducible and
    stateless.
    """
    blocks: List[str] = [_symbol_header(task), _support_block(task.support)]

    if history:
        lines = [
            "Your attempts so far in THIS puzzle, with the correct answers:"
        ]
        for i, (h_in, h_pred, h_gold) in enumerate(history, start=1):
            lines.append(f"  Attempt {i}:")
            lines.append(f"    Input:   {fmt_seq(h_in)}")
            lines.append(
                f"    Your answer: {h_pred if h_pred is not None else '(unparseable)'}"
            )
            lines.append(f"    Correct answer: {fmt_seq(h_gold)}")
            verdicts = "correct" if h_pred == fmt_seq(h_gold) else "INCORRECT"
            lines.append(f"    Verdict: {verdicts}")
        lines.append(
            "Use the corrections above to revise your understanding of the "
            "hidden rules before answering the next question."
        )
        blocks.append("\n".join(lines))
    else:
        blocks.append(
            "You will answer several questions. After each one you will be "
            "told whether you were right and what the correct answer was."
        )

    blocks.append(_question_block(index, total, inp))
    blocks.append(ANSWER_INSTRUCTION)
    return Prompt(system=SYSTEM_PROMPT, user=_join(*blocks))


# --------------------------------------------------------------------------
# Phase D -- explicit-rule control
# --------------------------------------------------------------------------


def build_phase_d(task: Task, index: int, total: int, inp: Seq) -> Prompt:
    """The same universe with its rules spelled out in English.

    This is the discriminant-validity control, and it is the design element
    that lets us separate *learning* from *rule execution*.

    Phase D - Phase B is the Induction Gap. A model whose gap is near zero can
    both execute and induce. A model that aces D but stalls on B is executing
    fine and failing to learn -- which is the specific failure mode a Learning
    benchmark exists to detect. Without D we could not tell those two models
    apart.
    """
    rules_text = "The hidden rules for THIS puzzle, in order:\n" + task.universe.rule_listing()
    user = _join(
        _symbol_header(task),
        rules_text,
        "Apply those rules, in that order, each exactly once.",
        _question_block(index, total, inp),
        ANSWER_INSTRUCTION,
    )
    return Prompt(system=SYSTEM_PROMPT, user=user)
