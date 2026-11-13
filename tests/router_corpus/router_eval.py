"""Score a prompt classifier against the labeled corpus in this folder.

    python tests/router_corpus/router_eval.py [split] [--errors] [--check]

scores the plugin's router_classifier; tests/test_router_corpus.py runs the regression check in CI.

A corpus row is one JSON object per line: id, prompt, lang, expect (chore / standard / deep / none),
alt (other tiers a reasonable person would accept), tags, note. A prediction counts as right when it is
`expect` or one of `alt`; in the confusion matrix a right prediction is booked under `expect`.

Splits. Each `blind*.jsonl` was written by another model that never saw the router's vocabulary and is its
own split, scored once on a frozen classifier. A blind set read while tuning stops being held out (blind.jsonl
was used to tune v2; blind2.jsonl is the fresh one). Every other row goes to `tune` or `holdout` (30%) by a hash of its
prompt, so the split can't be hand-picked; rows tagged `sanity` or `seed` are known regression cases and
always sit in `tune`.
"""

import glob
import hashlib
import json
import os
import time

TIERS = ("chore", "standard", "deep", "none")
# What the acceptance criteria ask for, checked by `eval --check` (and so by CI).
MIN_RECALL = {"deep": 0.90, "chore": 0.85}
MAX_FALSE_NUDGE = 0.03


def default_corpus():
    """The folder this file sits in."""
    return os.path.dirname(os.path.abspath(__file__))


def split_of(row, source):
    if source.startswith("blind"):
        return source
    if {"sanity", "seed"} & set(row.get("tags") or []):
        return "tune"
    digest = hashlib.sha256(row["prompt"].encode("utf-8")).hexdigest()
    return "holdout" if int(digest[:8], 16) % 10 < 3 else "tune"


def load(corpus_dir=None):
    rows = []
    for path in sorted(glob.glob(os.path.join(corpus_dir or default_corpus(), "*.jsonl"))):
        source = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    row = json.loads(line)
                    row["source"], row["split"] = source, split_of(row, source)
                    rows.append(row)
    return rows


def evaluate(classify, rows):
    """Run `classify(prompt) -> (tier or None, signals)` over the rows and return the metrics."""
    matrix = {e: {p: 0 for p in TIERS} for e in TIERS}
    errors, times = [], []
    for row in rows:
        start = time.perf_counter()
        tier, signals = classify(row["prompt"])[:2]
        times.append(time.perf_counter() - start)
        pred = tier or "none"
        right = pred == row["expect"] or pred in (row.get("alt") or [])
        matrix[row["expect"]][row["expect"] if right else pred] += 1
        if not right:
            errors.append({"id": row["id"], "expect": row["expect"], "pred": pred, "signals": signals,
                           "prompt": row["prompt"], "split": row["split"]})
    out = {"n": len(rows), "matrix": matrix, "errors": errors, "recall": {}, "precision": {}}
    for tier in TIERS:
        expected = sum(matrix[tier].values())
        predicted = sum(matrix[e][tier] for e in TIERS)
        out["recall"][tier] = matrix[tier][tier] / expected if expected else None
        out["precision"][tier] = matrix[tier][tier] / predicted if predicted else None
    # A nudge is a chore or deep label: on the default setup (Sonnet, medium) those are the labels that
    # make the router speak. False-nudge rate = wrong chore/deep labels on prompts that should be none or
    # standard. False-label rate = any wrong label on a prompt that should be silent (what an Opus or
    # Fable session would see, where standard speaks too).
    quiet = sum(sum(matrix[e].values()) for e in ("none", "standard"))
    nudged = sum(matrix[e][p] for e in ("none", "standard") for p in ("chore", "deep"))
    silent = sum(matrix["none"].values())
    out["false_nudge"] = nudged / quiet if quiet else None
    out["false_label"] = (silent - matrix["none"]["none"]) / silent if silent else None
    out["accuracy"] = sum(matrix[t][t] for t in TIERS) / len(rows) if rows else None
    times.sort()
    out["p95_ms"] = 1000 * times[int(0.95 * (len(times) - 1))] if times else None
    return out


def pct(value):
    return "  n/a" if value is None else f"{100 * value:5.1f}%"


def format_report(name, result, show_errors=False):
    lines = [f"== {name}: {result['n']} prompts, accuracy {pct(result['accuracy']).strip()} =="]
    lines.append("expected \\ predicted " + "".join(f"{t:>10}" for t in TIERS))
    for e in TIERS:
        lines.append(f"{e:<20} " + "".join(f"{result['matrix'][e][p]:>10}" for p in TIERS))
    lines.append("recall     " + "  ".join(f"{t} {pct(result['recall'][t]).strip()}" for t in TIERS))
    lines.append("precision  " + "  ".join(f"{t} {pct(result['precision'][t]).strip()}" for t in TIERS))
    lines.append(f"false-nudge rate (chore/deep label on a none/standard prompt): "
                 f"{pct(result['false_nudge']).strip()}")
    lines.append(f"false-label rate (any label on a prompt that should be silent): "
                 f"{pct(result['false_label']).strip()}")
    lines.append(f"classify time p95: {result['p95_ms']:.2f} ms")
    if show_errors:
        for err in result["errors"]:
            text = " ".join(err["prompt"].split())
            lines.append(f"  {err['id']} expected {err['expect']}, got {err['pred']} "
                         f"{err['signals']}: {text[:110]}")
    return "\n".join(lines)


def failed_criteria(result):
    """The acceptance criteria this result misses, as text; empty when it meets all of them."""
    failed = []
    for tier, floor in MIN_RECALL.items():
        if result["recall"][tier] is not None and result["recall"][tier] < floor:
            failed.append(f"{tier} recall {pct(result['recall'][tier]).strip()} < {floor:.0%}")
    if result["false_nudge"] is not None and result["false_nudge"] > MAX_FALSE_NUDGE:
        failed.append(f"false-nudge rate {pct(result['false_nudge']).strip()} > {MAX_FALSE_NUDGE:.0%}")
    return failed


def run(classify, corpus_dir=None, split="all", show_errors=False, check=False):
    """Print the report for one split (or each of them) and return the exit code."""
    rows = load(corpus_dir)
    if not rows:
        print(f"no corpus found in {corpus_dir or default_corpus()}")
        return 2
    found = sorted({r["split"] for r in rows if r["split"].startswith("blind")})
    names = ("tune", "holdout", *found) if split == "all" else (split,)
    code = 0
    for name in names:
        part = [r for r in rows if r["split"] == name]
        if not part:
            continue
        result = evaluate(classify, part)
        print(format_report(name, result, show_errors))
        missed = failed_criteria(result)
        print("criteria: " + ("met" if not missed else "MISSED - " + "; ".join(missed)) + "\n")
        if check and missed:
            code = 1
    return code


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(default_corpus(), "..", "..", "plugins", "joao-kit", "hooks"))
    import router_classifier
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(run(router_classifier.classify, split=args[0] if args else "all",
                 show_errors="--errors" in sys.argv, check="--check" in sys.argv))
