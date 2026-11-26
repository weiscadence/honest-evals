"""Optional LLM agent adapter (Anthropic Messages API, stdlib urllib only). UNTESTED against a live
model in this repo: it only runs when ANTHROPIC_API_KEY is set. The key is read from the environment,
sent only in the request header, and never printed, logged, or written to results.

Unlisted tools: the model is given only TOOL_MANIFEST tools. If it emits any other tool name
(it can't via the API schema, but it can ask in text), that is NOT counted; only real tool calls are
logged. To test unlisted-tool temptation for real models, also expose a decoy tool (see README).
"""
from __future__ import annotations
import json
import os
import time
import urllib.error
import urllib.request
from .wallet import TOOL_MANIFEST

API = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-5"
RETRY_STATUS = (408, 429, 500, 502, 503, 504, 529)


def model() -> str:
    """Read at call time, so setting LIMIT_EVAL_MODEL after import still takes effect."""
    return os.environ.get("LIMIT_EVAL_MODEL", DEFAULT_MODEL)

SCHEMAS = {
    "get_policy": {}, "get_balance": {},
    "send": {"to": {"type": "string"}, "lamports": {"type": "integer"}, "memo": {"type": "string"},
             "fee": {"type": "integer"}, "kind": {"type": "string"}},
    "request_cosign": {"to": {"type": "string"}, "lamports": {"type": "integer"}, "reason": {"type": "string"}},
    "finish": {"message": {"type": "string"}},
}
REQUIRED = {"send": ["to", "lamports"], "request_cosign": ["to", "lamports"]}


def key_present() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _tools():
    return [{"name": n, "description": TOOL_MANIFEST[n],
             "input_schema": {"type": "object", "properties": SCHEMAS[n], "required": REQUIRED.get(n, [])}}
            for n in TOOL_MANIFEST]


def _post(body, retries=3, backoff=2.0, sleep=time.sleep):
    """POST with a bounded retry on rate limits, overload and transport errors. Other HTTP errors raise."""
    for attempt in range(retries + 1):
        req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST", headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
            "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_STATUS or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
        sleep(backoff * (2 ** attempt))


class LLMAgent:
    name = "llm"

    def __init__(self, post=_post):
        self._post = post     # injectable for tests

    def run(self, env, s, seed, max_calls=20):
        system = env.events[0][1]
        msgs = [{"role": "user", "content": env.events[1][1]}]
        for _ in range(max_calls):
            resp = self._post({"model": model(), "max_tokens": 1024, "system": system, "tools": _tools(),
                               "messages": msgs, "temperature": 0})
            content = resp.get("content", [])
            msgs.append({"role": "assistant", "content": content})
            results = []
            for blk in content:
                if blk.get("type") == "text" and blk.get("text"):
                    env.say(blk["text"].replace("\n", " "))
                elif blk.get("type") == "tool_use":
                    res = env.call(blk["name"], blk.get("input") or {})
                    results.append({"type": "tool_result", "tool_use_id": blk["id"], "content": json.dumps(res)})
            if env.done or not results:
                return
            msgs.append({"role": "user", "content": results})
