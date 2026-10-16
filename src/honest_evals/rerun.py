"""Re-execute a claim's read-only check and classify the outcome.

Classes (``RerunClass``):

* ``still_true``       - the check reproduces the observed value today.
* ``drifted``          - the value differs because the data legitimately
                         changed since claim time (append-only logs, live
                         boards). Never an error at publish. Requires a
                         ``DriftAdjudication`` bound to the ledger record: it
                         carries the record's ``seq`` and its recorded ``hash``,
                         and the hash is recomputed from the record's fields.
* ``wrong_at_publish`` - the claim disagreed with its own check *when it was
                         made*. Established either by an explicit adjudication
                         or by record-consistency: the record carries the value
                         the claim asserted (``expected``) and it differs from
                         the value the check produced at the time (``observed``).
* ``not_rerunnable``   - refused (not allowlisted, no command, timeout, crash) or a
                         mismatch nobody has adjudicated. Always carries a
                         named reason. These rows count as *unresolved* in the
                         denominator, never as true.

A mismatch is deliberately never auto-classified as drift: that would turn the
drift bucket into a place to hide errors. No free text on the record can do it
either: ``snapshot`` / ``snapshot_reason`` are caller-controlled fields and are
ignored for classification (they are only echoed into the reason). A plain
``Adjudication`` cannot carry ``DRIFTED``; only a ``DriftAdjudication`` whose
``seq`` and ``record_hash`` match the record (and the hash recomputed from the
record's fields) classifies as drift. Anything else is returned as
``not_rerunnable`` with a named reason so it stays visible as unresolved.

Comparison strips leading/trailing whitespace only (a trailing newline is not
a difference) and preserves internal runs: ``"a  b"`` is not ``"a b"``. Pass
``collapse_whitespace=True`` to opt in to collapsing runs; the result's reason
says so.
"""
from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Sequence, Union

__all__ = [
    "Adjudication",
    "ALLOWLIST",
    "DriftAdjudication",
    "RerunClass",
    "RerunResult",
    "refusal_reason",
    "rerun",
    "rerun_many",
]


class RerunClass(str, Enum):
    STILL_TRUE = "still_true"
    DRIFTED = "drifted"
    WRONG_AT_PUBLISH = "wrong_at_publish"
    NOT_RERUNNABLE = "not_rerunnable"


# Allowlist: a command may run only if every pipeline stage is one of these
# read-only programs, with only the arguments allowed below. Everything else is
# refused with a named reason. This is still not a sandbox: an allowed command is
# run with a timeout under `nice`, and the caller chooses cwd.
ALLOWLIST: frozenset[str] = frozenset(
    {
        "echo", "printf", "cat", "wc", "grep", "egrep", "fgrep", "head", "tail", "ls", "sort",
        "uniq", "cut", "tr", "jq", "sha256sum", "sha1sum", "md5sum", "stat", "test", "[",
        "date", "true", "false", "sleep", "basename", "dirname", "realpath", "diff", "cmp",
        "comm", "nl", "file", "du", "df", "pwd", "seq", "git",
    }
)
# Per-command argument prefixes that write files or run other programs.
_ARG_DENY: dict[str, tuple[str, ...]] = {
    "sort": ("-o", "--output", "--compress-program"),
    "date": ("-s", "--set"),
    "tail": ("-f", "-F", "--follow"),
    "diff": ("--to-file", "--from-file"),
}
_GIT_READ = frozenset({"log", "show", "grep", "status", "diff", "rev-parse", "ls-files", "cat-file", "describe", "branch", "tag"})
_GIT_ARG_DENY = ("--output", "-O", "--open-files-in-pager", "--ext-diff", "--textconv", "--exec", "--upload-pack", "--receive-pack")
# `git branch` / `git tag` are read-only only as listings.
_GIT_LIST_FLAGS = {
    "branch": frozenset({"--list", "-l", "-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose", "--show-current", "--no-color", "--color=never"}),
    "tag": frozenset({"--list", "-l", "-n"}),
}
_METACHARS = set("$`\\;<>(){}~\n\r")
_NETWORK_HINT = re.compile(r"https?://|wss?://|ftp://|/dev/(tcp|udp)/", re.IGNORECASE)
_SEPARATORS = frozenset({"|", "&&"})


def _tokens(cmd: str) -> list[str]:
    lex = shlex.shlex(cmd, posix=True, punctuation_chars="|&")
    lex.whitespace_split = True
    return list(lex)


def _check_stage(argv: list[str]) -> Optional[str]:
    prog = argv[0]
    if "/" in prog or "=" in prog:
        return f"not_allowlisted:{prog}"
    if prog not in ALLOWLIST:
        return f"not_allowlisted:{prog}"
    args = argv[1:]
    for a in args:
        if a.startswith(_ARG_DENY.get(prog, ())):
            return f"not_allowlisted:{prog}_{a.split('=', 1)[0]}"
    if prog == "git":
        if not args or args[0].startswith("-"):
            return "not_allowlisted:git_global_option" if args else "not_allowlisted:git_no_subcommand"
        sub, rest = args[0], args[1:]
        if sub not in _GIT_READ:
            return f"not_allowlisted:git_{sub}"
        for a in rest:
            if a.startswith(_GIT_ARG_DENY):
                return f"not_allowlisted:git_{sub}_{a.split('=', 1)[0]}"
        if sub in _GIT_LIST_FLAGS and any(a not in _GIT_LIST_FLAGS[sub] for a in rest):
            return f"not_allowlisted:git_{sub}_write_form"
    return None


def refusal_reason(cmd: str) -> Optional[str]:
    """Return a named reason to refuse ``cmd``, or ``None`` if it may run.

    Allowlist, not denylist: the command must be a pipeline (``|``) or ``&&``
    chain of allowlisted read-only programs. Any shell metacharacter that can
    substitute, expand, redirect, group or sequence (``$ ` \\ ; < > ( ) { } ~``,
    newlines, a lone ``&``) is refused anywhere in the string, even inside
    quotes. The only redirect accepted is a literal ``2>&1``. Shell builtins
    that run other code (``eval``, ``exec``, ``source``, ``command``, ...) and
    interpreters (``python3 -c``, ...) are simply not on the allowlist.
    """
    if not cmd or not cmd.strip():
        return "no_command_recorded"
    if _NETWORK_HINT.search(cmd):
        return "refused:network"
    stripped = re.sub(r"(?<!\S)2>&1(?!\S)", " ", cmd)
    bad = sorted({c for c in stripped if c in _METACHARS})
    if bad:
        return "refused:shell_metachar:" + "".join(repr(c)[1:-1] for c in bad)
    try:
        toks = _tokens(stripped)
    except ValueError:
        return "refused:unparseable"
    stage: list[str] = []
    stages: list[list[str]] = []
    for t in toks:
        if t and set(t) <= {"|", "&"}:
            if t not in _SEPARATORS or not stage:
                return f"refused:shell_operator:{t}"
            stages.append(stage)
            stage = []
        else:
            stage.append(t)
    if not stage:
        return "refused:dangling_operator"
    stages.append(stage)
    for st in stages:
        why = _check_stage(st)
        if why:
            return why
    return None


@dataclass(frozen=True)
class Adjudication:
    """A human-written verdict on a specific mismatch, with evidence.

    ``DRIFTED`` is not accepted here: drift must be a ``DriftAdjudication``
    bound to a ledger record.
    """

    cls: RerunClass
    evidence: str
    strict: bool = False
    lenient: bool = False

    def __post_init__(self) -> None:
        if self.cls is RerunClass.DRIFTED and not isinstance(self, DriftAdjudication):
            raise TypeError("drift must be a DriftAdjudication bound to a ledger record (seq + record hash); free text is not enough")


@dataclass(frozen=True)
class DriftAdjudication(Adjudication):
    """A drift verdict bound to one ledger record.

    ``record_hash`` is the record's ledger ``hash`` and ``seq`` its sequence
    number; ``rerun`` refuses to classify drift unless both match the record
    *and* the hash recomputes from the record's fields (so an edited record
    does not inherit an earlier adjudication). Positional order is
    ``(record_hash, seq, evidence)``.
    """

    record_hash: str = ""
    seq: Any = None
    evidence: str = ""
    cls: RerunClass = RerunClass.DRIFTED
    strict: bool = False
    lenient: bool = False

    def __init__(self, record_hash: str, seq: Any, evidence: str, *, lenient: bool = False) -> None:
        if not str(evidence).strip():
            raise ValueError("a DriftAdjudication needs non-empty evidence")
        object.__setattr__(self, "record_hash", str(record_hash))
        object.__setattr__(self, "seq", seq)
        object.__setattr__(self, "evidence", str(evidence))
        object.__setattr__(self, "cls", RerunClass.DRIFTED)
        object.__setattr__(self, "strict", False)
        object.__setattr__(self, "lenient", bool(lenient))

    def binding_failure(self, record: Mapping[str, Any]) -> Optional[str]:
        """Why this adjudication is not bound to ``record``, or ``None``."""
        recorded = str(record.get("hash") or "")
        if not self.record_hash or not recorded:
            return "drift_adjudication_unbound: record carries no ledger hash"
        if record.get("seq") != self.seq:
            return f"drift_adjudication_unbound: adjudicated seq {self.seq!r} is not record seq {record.get('seq')!r}"
        if recorded != self.record_hash:
            return "drift_adjudication_unbound: adjudicated hash is not the record's hash"
        try:
            from .ledger import Claim, hash_record

            fields = {k: record.get(k) for k in ("seq", "ts", "claim", "check", "observed", "kind", "prev")}
            fields["meta"] = record.get("meta") or {}
            recomputed = hash_record(Claim.from_dict({**fields, "hash": ""}))
        except (KeyError, TypeError, ValueError):
            return "drift_adjudication_unbound: record lacks the ledger fields needed to recompute its hash"
        if recomputed != self.record_hash:
            return "drift_adjudication_unbound: record fields do not hash to the adjudicated hash (edited after adjudication?)"
        return None


@dataclass(frozen=True)
class RerunResult:
    seq: Any
    cls: RerunClass
    reason: str
    observed: str
    rerun: Optional[str] = None
    strict: bool = False
    lenient: bool = False
    ms: Optional[int] = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def checked(self) -> bool:
        return self.cls is not RerunClass.NOT_RERUNNABLE

    @property
    def drift(self) -> bool:
        return self.cls is RerunClass.DRIFTED


def _norm(value: Any, *, collapse: bool = False) -> str:
    """Strip the ends; collapse internal whitespace runs only when asked."""
    s = str(value if value is not None else "")
    return (re.sub(r"\s+", " ", s) if collapse else s).strip()


def _run_shell(cmd: str, timeout: float, cwd: Optional[str], nice: int) -> tuple[Optional[str], Optional[str], int]:
    import time

    argv = ["nice", "-n", str(nice), "sh", "-c", cmd]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd, check=False)
    except subprocess.TimeoutExpired:
        return None, f"timeout_after_{timeout:g}s", int((time.monotonic() - t0) * 1000)
    except OSError as exc:
        return None, f"spawn_failed:{exc.__class__.__name__}", int((time.monotonic() - t0) * 1000)
    ms = int((time.monotonic() - t0) * 1000)
    if proc.returncode != 0:
        return proc.stdout, f"exit_{proc.returncode}", ms
    return proc.stdout, None, ms


def rerun(
    record: Mapping[str, Any],
    *,
    timeout: float = 30.0,
    cwd: Optional[str] = None,
    nice: int = 10,
    adjudication: Optional[Adjudication] = None,
    callables: Optional[Mapping[str, Callable[[], Any]]] = None,
    compare: Optional[Callable[[str, str], bool]] = None,
    collapse_whitespace: bool = False,
) -> RerunResult:
    """Re-run one claim record and classify it.

    ``record`` needs ``check`` (shell command or ``callable:<name>`` resolved via
    ``callables``) and ``observed``. Optional: ``seq``, ``expected`` (what the
    claim asserted; enables the record-consistency check). ``snapshot`` and
    ``snapshot_reason`` on the record never classify anything; a mismatch is
    drift only under a ``DriftAdjudication`` bound to the record's ledger hash.

    Values are compared after stripping leading/trailing whitespace. Internal
    whitespace runs count as differences unless ``collapse_whitespace=True``.
    """
    seq = record.get("seq")
    observed = _norm(record.get("observed"), collapse=collapse_whitespace)
    check = str(record.get("check") or record.get("cmd") or "")
    expected = record.get("expected")
    collapsed_note = " (whitespace runs collapsed)" if collapse_whitespace else ""
    eq = compare or (lambda a, b: _norm(a, collapse=collapse_whitespace) == _norm(b, collapse=collapse_whitespace))

    # Record-consistency first: this needs no execution and catches claims that
    # disagreed with their own output at publish time.
    if expected is not None and not eq(str(expected), observed):
        adj = adjudication
        return RerunResult(
            seq, RerunClass.WRONG_AT_PUBLISH,
            "record_inconsistent: claim asserted a value its own check did not produce at the time",
            observed, strict=True, lenient=bool(adj.lenient) if adj else False,
        )

    # Execute.
    rerun_value: Optional[str]
    ms: Optional[int] = None
    if check.startswith("callable:"):
        name = check[len("callable:"):]
        fn = (callables or {}).get(name)
        if fn is None:
            return RerunResult(seq, RerunClass.NOT_RERUNNABLE, f"callable_not_provided:{name}", observed)
        try:
            rerun_value = _norm(fn(), collapse=collapse_whitespace)
        except Exception as exc:  # noqa: BLE001 - the reason is the point
            return RerunResult(seq, RerunClass.NOT_RERUNNABLE, f"callable_raised:{exc.__class__.__name__}", observed)
    else:
        why = refusal_reason(check)
        if why:
            return RerunResult(seq, RerunClass.NOT_RERUNNABLE, why, observed)
        out, err, ms = _run_shell(check, timeout, cwd, nice)
        if err is not None and out is None:
            return RerunResult(seq, RerunClass.NOT_RERUNNABLE, err, observed, ms=ms)
        rerun_value = _norm(out, collapse=collapse_whitespace)
        if err is not None:
            # non-zero exit: only trust it if the output still matches exactly.
            if eq(rerun_value, observed):
                return RerunResult(seq, RerunClass.STILL_TRUE, f"output_matches_despite_{err}{collapsed_note}", observed, rerun_value, ms=ms)
            return RerunResult(seq, RerunClass.NOT_RERUNNABLE, f"check_failed:{err}", observed, rerun_value, ms=ms)

    if eq(rerun_value, observed):
        # an adjudicated strict flag survives a matching re-run (stale restatement).
        if adjudication and adjudication.cls is RerunClass.WRONG_AT_PUBLISH:
            return RerunResult(seq, RerunClass.WRONG_AT_PUBLISH, f"adjudicated: {adjudication.evidence}", observed, rerun_value,
                               strict=adjudication.strict, lenient=adjudication.lenient, ms=ms)
        return RerunResult(seq, RerunClass.STILL_TRUE, f"rerun_matches_observed{collapsed_note}", observed, rerun_value, ms=ms)

    # Mismatch. Needs a structured verdict; drift additionally needs a ledger binding.
    if adjudication is not None:
        if adjudication.cls is RerunClass.DRIFTED:
            if not isinstance(adjudication, DriftAdjudication):
                return RerunResult(seq, RerunClass.NOT_RERUNNABLE, "drift_adjudication_unbound: not a DriftAdjudication",
                                   observed, rerun_value, ms=ms)
            why_unbound = adjudication.binding_failure(record)
            if why_unbound:
                return RerunResult(seq, RerunClass.NOT_RERUNNABLE, why_unbound, observed, rerun_value, ms=ms)
            return RerunResult(seq, RerunClass.DRIFTED,
                               f"adjudicated_drift[seq={adjudication.seq} hash={adjudication.record_hash[:12]}]: {adjudication.evidence}",
                               observed, rerun_value, lenient=adjudication.lenient, ms=ms)
        return RerunResult(seq, adjudication.cls, f"adjudicated: {adjudication.evidence}", observed, rerun_value,
                           strict=adjudication.strict, lenient=adjudication.lenient, ms=ms)
    note = ""
    if record.get("snapshot"):
        note = f"; record declares snapshot ({str(record.get('snapshot_reason') or '').strip() or 'no reason'!r}) but free text is not an adjudication"
    return RerunResult(seq, RerunClass.NOT_RERUNNABLE, f"mismatch_unadjudicated: rerun={rerun_value!r} observed={observed!r}{note}",
                       observed, rerun_value, ms=ms)


def rerun_many(
    records: Sequence[Mapping[str, Any]],
    *,
    adjudications: Optional[Mapping[Any, Adjudication]] = None,
    **kwargs: Any,
) -> list[RerunResult]:
    adj = adjudications or {}
    return [rerun(r, adjudication=adj.get(r.get("seq")), **kwargs) for r in records]
