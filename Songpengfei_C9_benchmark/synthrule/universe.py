"""
SynthRule — rule language and deterministic executor.

A *universe* is a small, self-contained rewriting system: a finite symbol
alphabet plus an **ordered** list of rules. Applying a universe to a sequence
means applying R1, then R2, ... then Rn, each exactly once, left to right.

Design constraints that matter for measurement validity
-------------------------------------------------------
1. **Deterministic and unambiguous.**  Sequences are lists of *symbols*, never
   raw strings.  This removes all substring ambiguity (important because
   pseudoword alphabets such as ``qa``/``zo`` contain multi-character tokens).
2. **Cheap to execute, hard to induce.**  Every primitive is trivial to apply
   once known.  The difficulty of the task therefore lives in *inferring* the
   rule list from examples, not in executing it.  This is what separates a
   Learning measurement from a Reasoning measurement.
3. **Simultaneous swap.**  ``swap(a, b)`` exchanges a and b at once; the naive
   two-pass implementation would silently cancel itself and produce wrong
   ground truth.

Author: Songpengfei
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

# --------------------------------------------------------------------------
# Symbol pools
# --------------------------------------------------------------------------
# Three alphabet families.  They exist to separate "this is hard to learn"
# from "this is hard to tokenize" -- see `alphabet_type` below.

# Unusual geometric glyphs: maximally unfamiliar, but multi-byte and therefore
# a potential tokenization confound.  Kept to widely-rendered characters.
GEOMETRIC_POOL: List[str] = list("▲●■◆★○□◇△▽◁▷◀▶◐◑")

# Familiar Latin letters: the *contamination probe* alphabet.  Single capital
# letters are heavily represented in pre-training, so a model that merely
# retrieves memorized transformations should do better here than on the other
# two pools.  I/L/O omitted to avoid visual confusion with 1/0.
LATIN_POOL: List[str] = list("ABCDEFGHJKMNPQRSTUVWXYZ")

# Pseudowords: novel as *rule systems*, yet made of ordinary Latin letters, so
# they tokenize cleanly.  This is the primary alphabet for the headline result.
PSEUDOWORD_POOL: List[str] = [
    c + v for c in "bdfgklmnprstvwz" for v in "aeiou"
]  # 75 distinct two-letter syllables

ALPHABET_POOLS: Dict[str, List[str]] = {
    "glyph": GEOMETRIC_POOL,
    "latin": LATIN_POOL,
    "pseudoword": PSEUDOWORD_POOL,
}

# --------------------------------------------------------------------------
# Rule primitives
# --------------------------------------------------------------------------

RULE_KINDS = (
    "substitute",
    "duplicate",
    "delete",
    "reverse",
    "reverse_if",
    "rotate_if_longer",
    "swap",
)


@dataclass(frozen=True)
class Rule:
    """A single rewriting primitive.

    `kind` selects the primitive; the remaining fields are its parameters.
    Instances are immutable and hashable so rule lists can be de-duplicated.
    """

    kind: str
    a: Optional[str] = None
    b: Optional[str] = None
    n: Optional[int] = None

    def __post_init__(self) -> None:
        if self.kind not in RULE_KINDS:
            raise ValueError(f"unknown rule kind: {self.kind!r}")
        if self.kind in ("substitute", "duplicate", "delete", "reverse_if"):
            if self.a is None:
                raise ValueError(f"{self.kind} requires parameter 'a'")
        if self.kind in ("substitute", "swap"):
            if self.b is None:
                raise ValueError(f"{self.kind} requires parameter 'b'")
        if self.kind == "rotate_if_longer" and self.n is None:
            raise ValueError("rotate_if_longer requires parameter 'n'")
        if self.kind == "swap" and self.a == self.b:
            raise ValueError("swap requires two distinct symbols")

    # -- execution ---------------------------------------------------------

    def apply(self, seq: Sequence[str]) -> List[str]:
        """Return a new list; never mutates the input."""
        s = list(seq)

        if self.kind == "substitute":
            return [self.b if t == self.a else t for t in s]

        if self.kind == "duplicate":
            out: List[str] = []
            for t in s:
                out.append(t)
                if t == self.a:
                    out.append(t)
            return out

        if self.kind == "delete":
            return [t for t in s if t != self.a]

        if self.kind == "reverse":
            return s[::-1]

        if self.kind == "reverse_if":
            return s[::-1] if self.a in s else s

        if self.kind == "rotate_if_longer":
            assert self.n is not None
            return s[1:] + s[:1] if len(s) > self.n else s

        if self.kind == "swap":
            # Simultaneous exchange -- a sequential two-pass swap would cancel.
            return [
                self.b if t == self.a else (self.a if t == self.b else t) for t in s
            ]

        raise AssertionError(f"unreachable: {self.kind!r}")

    # -- presentation ------------------------------------------------------

    def describe(self) -> str:
        """Deterministic English rendering. Used verbatim in the Phase-D prompt."""
        if self.kind == "substitute":
            return f"Replace every {self.a} with {self.b}."
        if self.kind == "duplicate":
            return f"Replace every {self.a} with two copies of itself ({self.a}{self.a})."
        if self.kind == "delete":
            return f"Delete every {self.a} from the sequence."
        if self.kind == "reverse":
            return "Reverse the entire sequence."
        if self.kind == "reverse_if":
            return (
                f"If the sequence contains {self.a}, reverse the entire sequence. "
                f"Otherwise leave the sequence unchanged."
            )
        if self.kind == "rotate_if_longer":
            return (
                f"If the sequence has more than {self.n} symbols, move the first "
                f"symbol to the end. Otherwise leave the sequence unchanged."
            )
        if self.kind == "swap":
            return (
                f"Swap every {self.a} with {self.b}, and every {self.b} with {self.a}."
            )
        raise AssertionError(f"unreachable: {self.kind!r}")

    # -- (de)serialisation -------------------------------------------------

    def to_dict(self) -> Dict[str, object]:
        d: Dict[str, object] = {"kind": self.kind}
        if self.a is not None:
            d["a"] = self.a
        if self.b is not None:
            d["b"] = self.b
        if self.n is not None:
            d["n"] = self.n
        return d

    @staticmethod
    def from_dict(d: Dict[str, object]) -> "Rule":
        return Rule(
            kind=str(d["kind"]),
            a=d.get("a"),  # type: ignore[arg-type]
            b=d.get("b"),  # type: ignore[arg-type]
            n=d.get("n"),  # type: ignore[arg-type]
        )

    def signature(self) -> str:
        """Canonical string used for de-duplication."""
        return f"{self.kind}:{self.a}:{self.b}:{self.n}"


# --------------------------------------------------------------------------
# Universes
# --------------------------------------------------------------------------


def apply_rules(seq: Sequence[str], rules: Sequence[Rule]) -> List[str]:
    """Apply `rules` in order, each exactly once. Pure function."""
    cur = list(seq)
    for r in rules:
        cur = r.apply(cur)
    return cur


@dataclass
class Universe:
    """A symbol alphabet plus an ordered rule list."""

    uid: str
    symbols: List[str]
    rules: List[Rule]
    alphabet_type: str = "pseudoword"
    difficulty: int = 0
    familiar: bool = False  # True for the contamination-probe condition

    def __post_init__(self) -> None:
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("symbols must be distinct")
        if any(("," in s or " " in s or "[" in s or "]" in s) for s in self.symbols):
            raise ValueError("symbols must not contain , space [ or ]")
        if self.difficulty == 0:
            self.difficulty = len(self.rules)

    def apply(self, seq: Sequence[str]) -> List[str]:
        return apply_rules(seq, self.rules)

    def render(self, seq: Sequence[str]) -> str:
        """Canonical on-screen form: ``[a, b, c]``."""
        return "[" + ", ".join(seq) + "]"

    def rule_listing(self) -> str:
        return "\n".join(
            f"  R{i + 1}. {r.describe()}" for i, r in enumerate(self.rules)
        )

    def fingerprint(self) -> str:
        """Content identity. Symbol order is preserved: two universes that
        differ only in how their alphabet is ordered are different puzzles."""
        return "|".join(self.symbols) + "||" + "|".join(
            r.signature() for r in self.rules
        )

    # -- (de)serialisation -------------------------------------------------

    def to_dict(self) -> Dict[str, object]:
        return {
            "uid": self.uid,
            "symbols": list(self.symbols),
            "rules": [r.to_dict() for r in self.rules],
            "alphabet_type": self.alphabet_type,
            "difficulty": self.difficulty,
            "familiar": self.familiar,
        }

    @staticmethod
    def from_dict(d: Dict[str, object]) -> "Universe":
        return Universe(
            uid=str(d["uid"]),
            symbols=list(d["symbols"]),  # type: ignore[arg-type]
            rules=[Rule.from_dict(r) for r in d["rules"]],  # type: ignore[union-attr]
            alphabet_type=str(d.get("alphabet_type", "pseudoword")),
            difficulty=int(d.get("difficulty", 0)),  # type: ignore[arg-type]
            familiar=bool(d.get("familiar", False)),
        )
