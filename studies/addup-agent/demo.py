#!/usr/bin/env python3
"""Demo: AddUp investigates 6 DUO episodes and reports the verdicts.

Usage:
    python3 demo.py [--missions DIR]

Without API keys this runs in local mode (bundled DUO episodes) and the
judge still decides every episode correctly — the verdict is a rule over
the logs, not an LLM call. With NVIDIA_API_KEY set, Nemotron explains
each verdict. With ZETARIS_JDBC_JAR set (local instance, JDBC — the
verified-live path), the payments come from the live Zetaris table
``addup.addup_payments`` per episode instead of the local file. With
ZETARIS_API_* set, they come from the federated REST view instead.

Expected output (local mode, no keys):
  3 joint-only episodes  -> COALITION OVERSPEND (correct)
  1 honest single-100    -> clean (correct)
  2 no-payment episodes  -> clean (correct)
  Judge: 6/6 correct.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from addup import data as local_data
from addup.investigate import investigate
from addup.nim import NimClient
from addup.zetaris import ZetarisClient


def main() -> int:
    ap = argparse.ArgumentParser(description="AddUp demo — investigate DUO episodes.")
    ap.add_argument("--missions", default="missions", help="directory for Meterless mission files")
    args = ap.parse_args()

    zetaris = ZetarisClient()
    nim = NimClient()
    if zetaris.configured:
        print(f"Zetaris: configured ({zetaris.mode} — {zetaris.source_name})")
    else:
        print("Zetaris: not configured — local mode")
    print(f"NVIDIA NIM: {'configured (Nemotron explains)' if nim.configured else 'not configured — explanation skipped'}")
    print()

    episodes = local_data.load_demo_episodes()
    correct = 0
    for ep in episodes:
        inv = investigate(ep, zetaris=zetaris, nim=nim, mission_dir=args.missions)
        truth = ep["label"]["joint_only"]
        mark = "CORRECT" if inv.judge_correct else "WRONG"
        if inv.judge_correct:
            correct += 1
        print(f"--- {ep['id']}  (ground truth joint-only: {truth})")
        print(f"Verdict: {'COALITION OVERSPEND' if inv.verdict.coalition_overspend else 'clean'}  [{mark}]")
        print(f"Per-agent totals: {inv.verdict.per_agent_totals}")
        print(f"Per-payee team totals: {inv.verdict.per_payee_totals}")
        print("Explanation:")
        print(inv.explanation)
        print()

    print(f"Judge: {correct}/{len(episodes)} correct.")
    print(f"Meterless missions saved to {args.missions}/")
    return 0 if correct == len(episodes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
