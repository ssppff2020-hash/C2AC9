"""
SynthRule — answerers: reference baselines and the LLM adapter.

The baselines are not decoration.  A raw accuracy number means nothing on its
own, so every reported model score is anchored between reference points we can
compute exactly:

* ``random``   -- samples a sequence from the puzzle's own alphabet. Establishes
  the true chance floor for this item distribution.
* ``oracle``   -- consults the ground-truth solver. Must score 1.000. Any
  deviation means the harness is broken, so this doubles as a pipeline check.
* ``identity`` -- echoes the input. Catches universes where doing nothing is
  accidentally right.
* ``align``    -- a shallow statistical inducer: position-aligned majority
  substitution, with no notion of ordering, conditions, or deletion. It is the
  strongest *non-learning* strategy we can specify, so it is the bar a genuine
  rule inducer has to clear.

A hard-won lesson about the LLM adapter
---------------------------------------
Reasoning models bill their chain-of-thought against ``max_tokens``.  With too
small a budget the API returns ``stop_reason="max_tokens"`` and a content list
containing only a ``thinking`` block -- no text at all.  Naively treating that
as a wrong answer manufactures a floor effect out of thin air: in our own first
pilot, 65 of 80 responses were empty for exactly this reason, and the model
appeared to score 0.000 on induction when it was in fact solving the puzzles.

So the adapter (a) budgets generously, (b) escalates the budget once when the
first attempt is cut off, and (c) reports every truncation explicitly instead
of folding it into the accuracy.  ``Reply.truncated`` exists so that "the model
failed" and "we cut the model off" can never be confused again.

Author: Songpengfei
"""

from __future__ import annotations

import os
import random
import threading
import time
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .prompts import Prompt

Seq = List[str]


@dataclass
class ItemContext:
    """Everything a non-LLM baseline may legitimately consult."""

    symbols: Seq
    inp: Seq
    gold: Seq
    support: List[tuple] = field(default_factory=list)  # [(input, output), ...]


@dataclass
class Reply:
    """A model's raw response plus the metadata needed to interpret it."""

    text: str
    stop_reason: str = "end_turn"
    attempts: int = 1

    @property
    def truncated(self) -> bool:
        """True when the response was cut off before an answer was emitted."""
        return self.stop_reason == "max_tokens"


# --------------------------------------------------------------------------
# Base
# --------------------------------------------------------------------------


class Agent(ABC):
    name: str = "agent"
    is_llm: bool = False

    @abstractmethod
    def answer(self, prompt: Prompt, ctx: ItemContext) -> Reply:
        """Return a Reply; the harness parses `.text` with the same parser it
        uses for every other agent, so all agents are scored identically."""

    def reset_task(self) -> None:
        """Hook for clearing per-puzzle state."""


# --------------------------------------------------------------------------
# Reference baselines
# --------------------------------------------------------------------------


class OracleAgent(Agent):
    """Ground truth. A score below 1.000 here means the harness is wrong."""

    name = "oracle"

    def answer(self, prompt: Prompt, ctx: ItemContext) -> Reply:
        return Reply("ANSWER: [" + ", ".join(ctx.gold) + "]")


class RandomAgent(Agent):
    """Uniform sample from the alphabet, with a length drawn from the observed
    support-output length distribution (falling back to 1..len(input)+2)."""

    name = "random"

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)
        # Phases run in a thread pool, so the RNG needs its own lock to stay
        # reproducible run-to-run.
        self._lock = threading.Lock()

    def answer(self, prompt: Prompt, ctx: ItemContext) -> Reply:
        lengths = [len(o) for _, o in ctx.support] or [len(ctx.inp)]
        with self._lock:
            if self.rng.random() < 0.5:
                length = self.rng.choice(lengths)
            else:
                length = self.rng.randint(0, len(ctx.inp) + 2)
            seq = [self.rng.choice(ctx.symbols) for _ in range(max(0, length))]
        return Reply("ANSWER: [" + ", ".join(seq) + "]")


class IdentityAgent(Agent):
    """Echoes the input unchanged."""

    name = "identity"

    def answer(self, prompt: Prompt, ctx: ItemContext) -> Reply:
        return Reply("ANSWER: [" + ", ".join(ctx.inp) + "]")


class AlignAgent(Agent):
    """Position-aligned majority substitution: the strongest non-learning
    strategy in our baseline set.

    For every support pair it pairs input[i] with output[i] up to the shorter
    length and counts the pair. The most frequent mapping per source symbol
    wins; unmapped symbols pass through. This captures plain substitution
    puzzles and nothing else -- it has no representation for rule order,
    conditional firing, insertion, or deletion.
    """

    name = "align"

    def __init__(self) -> None:
        # Keyed on the support content itself. Keying on id() would be a bug:
        # ItemContext objects are short-lived, so CPython can hand the same
        # address to a later context with completely different support.
        self._cache: Dict[Tuple, Dict[str, str]] = {}

    def _mapping(self, ctx: ItemContext) -> Dict[str, str]:
        key = tuple((tuple(i), tuple(o)) for i, o in ctx.support)
        if key in self._cache:
            return self._cache[key]
        counts: Dict[str, Counter] = {}
        for inp, out in ctx.support:
            for a, b in zip(inp, out):
                counts.setdefault(a, Counter())[b] += 1
        mapping = {a: c.most_common(1)[0][0] for a, c in counts.items()}
        self._cache[key] = mapping
        return mapping

    def answer(self, prompt: Prompt, ctx: ItemContext) -> Reply:
        if not ctx.support:
            return Reply("ANSWER: [" + ", ".join(ctx.inp) + "]")
        mapping = self._mapping(ctx)
        pred = [mapping.get(t, t) for t in ctx.inp]
        return Reply("ANSWER: [" + ", ".join(pred) + "]")


# --------------------------------------------------------------------------
# LLM adapter (Anthropic-compatible Messages API)
# --------------------------------------------------------------------------


class Usage:
    """Thread-safe accounting so cost and truncation can be reported honestly."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0
        self.errors = 0
        self.truncated = 0

    def add(self, inp: int, out: int, truncated: bool = False) -> None:
        with self._lock:
            self.input_tokens += inp
            self.output_tokens += out
            self.calls += 1
            if truncated:
                self.truncated += 1

    def error(self) -> None:
        with self._lock:
            self.errors += 1

    def as_dict(self) -> Dict[str, int]:
        return {
            "calls": self.calls,
            "errors": self.errors,
            "truncated_responses": self.truncated,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
        }


class LLMAgent(Agent):
    """Calls an Anthropic-compatible /v1/messages endpoint.

    Configuration is read from the environment, never hard-coded:

        ANTHROPIC_BASE_URL    e.g. https://api.deepseek.com/anthropic
        ANTHROPIC_AUTH_TOKEN  credential
        ANTHROPIC_MODEL       model id

    Retries on 429 and 5xx with exponential backoff, and escalates the token
    budget once if the model is cut off mid-reasoning.
    """

    is_llm = True

    def __init__(
        self,
        name: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        max_tokens: int = 16384,
        max_token_cap: int = 32768,
        temperature: float = 0.0,
        max_retries: int = 4,
        timeout: int = 600,
    ) -> None:
        import requests  # imported lazily so baselines run without the dep

        self._requests = requests
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "deepseek-v4-flash")
        self.base_url = (base_url or os.environ.get("ANTHROPIC_BASE_URL", "")).rstrip("/")
        self.token = token or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        if not self.base_url or not self.token:
            raise RuntimeError(
                "LLMAgent needs ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN in the environment"
            )
        self.name = name or f"llm:{self.model}"
        self.max_tokens = max_tokens
        self.max_token_cap = max_token_cap
        self.temperature = temperature
        self.max_retries = max_retries
        self.timeout = timeout
        self.usage = Usage()

    def _post(self, prompt: Prompt, budget: int):
        payload = {
            "model": self.model,
            "max_tokens": budget,
            "temperature": self.temperature,
            "system": prompt.system,
            "messages": [{"role": "user", "content": prompt.user}],
        }
        headers = {
            "content-type": "application/json",
            "x-api-key": self.token,
            "authorization": f"Bearer {self.token}",
            "anthropic-version": "2023-06-01",
        }

        delay = 2.0
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._requests.post(
                    f"{self.base_url}/v1/messages",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    return resp.json(), attempt + 1
                if resp.status_code in (429, 500, 502, 503, 504, 529):
                    pass  # retryable
                else:
                    return None, attempt + 1  # non-retryable
            except Exception:
                pass  # network / timeout / decode -> retry

            if attempt < self.max_retries:
                time.sleep(delay + random.random() * 0.5)
                delay = min(delay * 2, 30.0)

        return None, self.max_retries + 1

    def answer(self, prompt: Prompt, ctx: ItemContext) -> Reply:
        budget = self.max_tokens
        attempts = 0

        # Two escalations at most: enough to recover from a chain-of-thought
        # that overran, without paying to retry genuinely unbounded generation.
        for _ in range(3):
            data, used = self._post(prompt, budget)
            attempts += used

            if data is None:
                self.usage.error()
                return Reply("", stop_reason="error", attempts=attempts)

            u = data.get("usage", {}) or {}
            stop = data.get("stop_reason") or "end_turn"
            truncated = stop == "max_tokens"
            self.usage.add(
                int(u.get("input_tokens", 0) or 0),
                int(u.get("output_tokens", 0) or 0),
                truncated=truncated,
            )

            # Keep only text blocks: thinking/reasoning is not an answer and
            # must never be searched by the parser.
            parts = [
                b.get("text", "")
                for b in data.get("content", [])
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            text = "\n".join(p for p in parts if p).strip()

            if truncated and budget < self.max_token_cap:
                budget = min(budget * 2, self.max_token_cap)
                continue
            return Reply(text, stop_reason=stop, attempts=attempts)

        return Reply("", stop_reason="max_tokens", attempts=attempts)


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------

BASELINE_NAMES = ("oracle", "random", "identity", "align")


def make_agent(name: str, seed: int = 0) -> Agent:
    if name == "oracle":
        return OracleAgent()
    if name == "random":
        return RandomAgent(seed=seed)
    if name == "identity":
        return IdentityAgent()
    if name == "align":
        return AlignAgent()
    if name.startswith("llm"):
        model = name.split(":", 1)[1] if ":" in name else None
        return LLMAgent(model=model)
    raise ValueError(f"unknown agent {name!r}; expected one of {BASELINE_NAMES} or llm[:model]")
