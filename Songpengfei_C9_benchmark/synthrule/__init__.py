"""
SynthRule — a benchmark for measuring *genuine learning* in language models.

Track 1 (Learning), DeepMind x Kaggle "Measuring Progress Toward AGI:
Cognitive Abilities".

The question this package exists to answer:

    Can a model acquire a capability from a handful of examples, when the
    answer provably was not available to it beforehand -- or does it only
    appear to learn because the task resembles something already memorized?

Modules
-------
universe   rule language + deterministic executor (the ground-truth oracle)
generator  procedural task construction, validity gating, contamination probe
prompts    the four protocol phases (A prior / B induction / C feedback / D control)
agents     reference baselines + the LLM adapter
scoring    answer parsing and exact / partial credit
runner     orchestration, metrics, reporting

Author: Songpengfei
"""

__version__ = "1.0.0"
__author__ = "Songpengfei"

from .universe import Rule, Universe, apply_rules  # noqa: F401
from .generator import Task, build_task_set, make_task  # noqa: F401
from .scoring import parse_answer, score_answer  # noqa: F401
