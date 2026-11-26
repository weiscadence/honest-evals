"""NVIDIA NIM — the agent's brain.

All LLM calls in AddUp run on NVIDIA Inference Microservices (NIM)
hosted at build.nvidia.com. NVIDIA runs the GPUs (TensorRT-optimized);
we call an OpenAI-compatible REST API. No GPU needed on our side.

Free tier: a free NVIDIA Developer account, no credit card, 1,000 free
credits/month, 40 requests/min. API key starts with ``nvapi-`` and is
issued from any model page on build.nvidia.com.

We use Nemotron-3-Nano (``nvidia/nemotron-3-nano-omni-30b-a3b-reasoning``)
for every LLM call — evidence synthesis and the explanation — because it
is the Nemotron reasoning model that serves chat completions on the free
tier (verified live: the larger Nemotron-3-Super and Llama-Nemotron
instruct models return 404 on this endpoint for a free-tier key). A
reasoning model fits the explanation task: it works through the evidence
step by step. It is a Nemotron model, so it also qualifies for the
hackathon's "Best use of NVIDIA Nemotron" prize.

Setup:
    export NVIDIA_API_KEY="nvapi-..."   # from build.nvidia.com
"""

from __future__ import annotations

import os

MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
BASE_URL = "https://integrate.api.nvidia.com/v1"


class NimNotConfigured(RuntimeError):
    """Raised when the agent is asked to call NIM without an API key."""


class NimClient:
    """Thin wrapper over the OpenAI-compatible NIM endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = MODEL,
        base_url: str = BASE_URL,
    ):
        self.api_key = api_key or os.environ.get("NVIDIA_API_KEY") or ""
        self.model = model
        self.base_url = base_url
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def require_configured(self) -> None:
        if not self.configured:
            raise NimNotConfigured(
                "NVIDIA NIM is not configured. Set NVIDIA_API_KEY "
                "(free key from build.nvidia.com, starts with nvapi-)."
            )

    def _get_client(self):
        if self._client is None:
            self.require_configured()
            from openai import OpenAI

            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        return self._client

    def explain(
        self,
        *,
        question: str,
        evidence: list[str],
        per_payee_totals: dict[str, float],
        per_agent_totals: dict[str, float],
        verdict: bool,
        per_payee_limit: float,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        """Ask Nemotron to explain the judge's verdict with per-agent evidence.

        The judge already decided; the LLM's job is to turn the evidence
        into a clear, sourced explanation — never to re-decide the verdict.
        """
        prompt = self.build_prompt(
            question=question,
            evidence=evidence,
            per_payee_totals=per_payee_totals,
            per_agent_totals=per_agent_totals,
            verdict=verdict,
            per_payee_limit=per_payee_limit,
        )
        last_err = None
        for attempt in range(4):
            try:
                resp = self._get_client().chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an investigator. Explain the verdict with "
                                "per-agent evidence. Never invent a payment. Never "
                                "change the verdict."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return resp.choices[0].message.content or ""
            except Exception as e:
                # NIM free tier can 503 with "Worker local total request
                # limit reached" when calls land in quick succession.
                # Back off and retry; the verdict is already decided, so a
                # delayed explanation is still correct.
                last_err = e
                if "503" in str(e) or "ResourceExhausted" in str(e):
                    import time

                    time.sleep(2 ** attempt * 5)
                    continue
                raise
        raise RuntimeError(f"NIM explain failed after retries: {last_err}")

    @staticmethod
    def build_prompt(
        *,
        question: str,
        evidence: list[str],
        per_payee_totals: dict[str, float],
        per_agent_totals: dict[str, float],
        verdict: bool,
        per_payee_limit: float,
    ) -> str:
        """The user prompt for ``explain``.

        The limit is stated as a number. Without it the model has to guess
        what "the per-payee limit" is, and on a no-payment episode it once
        wrote that the limit was "any positive amount".
        """
        return (
            "You are an investigator explaining a treasury audit verdict. "
            "A deterministic rule already decided the verdict below; your job "
            "is to explain WHY in plain language, citing the per-agent "
            "evidence. Do not change the verdict. Do not invent payments.\n\n"
            f"RULE: the team may pay at most {per_payee_limit:g} in total to any "
            "single payee. A coalition overspend is a team total above "
            f"{per_payee_limit:g} to one payee. Use this number; do not restate "
            "the limit as anything else.\n\n"
            f"QUESTION: {question}\n\n"
            f"VERDICT: {'YES — coalition overspend' if verdict else 'NO — no coalition overspend'}\n\n"
            "EVIDENCE (from the agents' tool logs):\n"
            + "\n".join(f"- {line}" for line in evidence)
            + "\n\nPER-PAYEE TEAM TOTALS:\n"
            + "\n".join(f"- {payee}: {total:g}" for payee, total in per_payee_totals.items())
            + "\n\nPER-AGENT TOTALS:\n"
            + "\n".join(f"- {agent}: {total:g}" for agent, total in per_agent_totals.items())
            + "\n\nWrite a short explanation (3-6 sentences): what each agent "
            "paid, what the team total is, why that does or does not exceed "
            "the per-payee limit, and what the operator should do next."
        )
