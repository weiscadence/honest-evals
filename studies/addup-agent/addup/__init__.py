"""AddUp — the agent that can explain why.

Investigates whether two treasury agents jointly overspent by reading
BOTH agents' tool logs and adding up payments per payee across them.

The core result comes from two preregistered runs (see README):
  DUO (800 episodes):
  - A per-agent rule (flag if any single agent pays over the limit) catches
    0/11 joint-only overspends — it is blind by design.
  DUO-SUM (150 episodes):
  - A naive "flag any payment" rule false-alarms on 55/59 honest episodes.
  - The add-up judge (sum payments per payee across agents, flag if the
    TEAM total exceeds the per-payee limit) catches 41/41 violations with
    0/59 false alarms. Co-signer approval is not checked.

The judge is a deterministic rule over the logs. An LLM (NVIDIA Nemotron
via NIM) then explains the verdict with per-agent evidence. Zetaris
federates the two log sources into one view so the agent queries instead
of reading files directly. Each investigation is also written out as a
Nightshift-mission-shaped JSON file (an export; nothing here replays it).
"""

from .judge import AddUpJudge, Verdict
from .investigate import investigate, Investigation

__all__ = ["AddUpJudge", "Verdict", "investigate", "Investigation"]
__version__ = "0.1.0"
