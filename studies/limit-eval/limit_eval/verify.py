"""One-command receipt check: python -m limit_eval.verify [--committed results] [--readme README.md]

Re-runs the scripted baseline (5 seeds) into a temp dir, then checks:
  1. results/episodes.jsonl and results/baseline.md in the repo are byte-identical to the re-run (sha256);
  2. every number the README's "Baseline results" summary quotes appears in the re-run baseline.md
     as a whole token ("34/136" does not match "134/136"), and numbers the README ties to an agent
     or a threshold are checked against that agent's or threshold's row.
Prints one line per check and exits 0 only if all pass. No network, no keys, standard library only.
"""
import argparse, hashlib, os, re, sys, tempfile, contextlib, io

from . import run as R

FILES = ("episodes.jsonl", "baseline.md")


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def readme_numbers(readme_text):
    """The exact counts the README summary quotes: 'x/y' pairs and '[a, b]' intervals in the summary block."""
    m = re.search(r"## Baseline results.*?(?=\n## )", readme_text, re.S)
    block = m.group(0) if m else ""
    fracs = re.findall(FRAC, block)
    ivals = re.findall(IVAL, block)
    return fracs, ivals


FRAC = r"(?<![\d/.])\d+/\d+(?![\d/]|\.\d)"
IVAL = r"\[\d\.\d{3}, \d\.\d{3}\]"


def tokens(text):
    """Whole 'x/y' and '[a, b]' tokens in text. Membership in this set is exact, not substring."""
    return set(re.findall(FRAC, text)) | set(re.findall(IVAL, text))


def baseline_fields(base):
    """Per-field values from baseline.md: agent -> attempts, threshold -> (recall, recall CI, precision)."""
    agents, thresholds = {}, {}
    for ln in base.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) == 3 and re.fullmatch(r"\d+", cells[1]):
            m = re.match(FRAC, cells[2])
            if m: agents[cells[0]] = m.group(0)
        elif len(cells) == 8 and re.fullmatch(r"\d\.\d+", cells[0]):
            rec, prec = re.match(FRAC, cells[6]), re.match(FRAC, cells[7])
            ci = re.search(IVAL, cells[6])
            thresholds[cells[0]] = (rec.group(0) if rec else None, ci.group(0) if ci else None,
                                    prec.group(0) if prec else None)
    return agents, thresholds


def readme_fields(readme_text):
    """Claims in the README summary that name their field: [(description, kind, key, quoted value)]."""
    m = re.search(r"## Baseline results.*?(?=\n## |\Z)", readme_text, re.S)
    block = m.group(0) if m else ""
    out = []
    for agent, frac in re.findall(r"\b(honest|sneaky|mixed) (\d+/\d+)", block):
        out.append((f"{agent} attempts", "agent", agent, frac))
    for t, rest in re.findall(r"\b[Aa]t (\d\.\d): ([^\n]*?)(?=\. At |\.\s*$|\n|$)", block, re.M):
        r = re.search(r"(\d+/\d+) recall(?: (" + IVAL + r"))?", rest)
        if r:
            out.append((f"recall at {t}", "recall", t, r.group(1)))
            if r.group(2): out.append((f"recall interval at {t}", "recall_ci", t, r.group(2)))
        pr = re.search(r"(\d+/\d+) precision", rest)
        if pr: out.append((f"precision at {t}", "precision", t, pr.group(1)))
    return out


def field_mismatches(readme_text, base):
    agents, thresholds = baseline_fields(base)
    bad = []
    for desc, kind, key, quoted in readme_fields(readme_text):
        if kind == "agent":
            actual = agents.get(key)
        else:
            actual = (thresholds.get(key) or (None, None, None))[("recall", "recall_ci", "precision").index(kind)]
        if actual != quoted:
            bad.append(f"{desc}: README {quoted}, re-run {actual}")
    return bad


def check(committed="results", readme="README.md", seeds=5, out=None):
    lines, ok = [], True
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            R.main(["--seeds", str(seeds), "--out", tmp])
        for name in FILES:
            a, b = os.path.join(committed, name), os.path.join(tmp, name)
            if not os.path.exists(a):
                ok = False; lines.append(f"FAIL {name}: missing from {committed}/"); continue
            same = sha(a) == sha(b)
            ok &= same
            lines.append(f"{'MATCH' if same else 'FAIL'} {name}: committed {sha(a)[:16]} vs re-run {sha(b)[:16]}")
        base = open(os.path.join(tmp, "baseline.md")).read()
        fracs, ivals = readme_numbers(open(readme).read())
        if not fracs:
            ok = False; lines.append("FAIL README: no numbers found in the 'Baseline results' section")
        have = tokens(base)
        missing = [x for x in fracs + ivals if x not in have]
        ok &= not missing
        lines.append(f"{'MATCH' if not missing else 'FAIL'} README summary: {len(fracs) + len(ivals) - len(missing)}/{len(fracs) + len(ivals)} quoted numbers found in re-run baseline.md"
                     + (f" (missing: {', '.join(missing)})" if missing else ""))
        bad = field_mismatches(open(readme).read(), base)
        ok &= not bad
        lines.append(f"{'MATCH' if not bad else 'FAIL'} README fields: agent and threshold numbers sit in their own rows"
                     + (f" (wrong: {'; '.join(bad)})" if bad else ""))
    lines.append("RECEIPTS REPRODUCE" if ok else "RECEIPTS DO NOT REPRODUCE")
    return ok, lines


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--committed", default="results")
    ap.add_argument("--readme", default="README.md")
    a = ap.parse_args(argv)
    ok, lines = check(a.committed, a.readme)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
