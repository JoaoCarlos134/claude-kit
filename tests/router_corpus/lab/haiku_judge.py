"""Lab variant E: Claude Haiku as the judge, one `claude -p` call per prompt, trimmed to the minimum.

Off by default and never run by CI (it spends real usage). The call is the cheapest form a hook could
make without an API key: own system prompt, no tools, no settings sources (so no plugin hooks, no
recursion), no MCP, no dynamic system-prompt sections. The instruction below was fixed before scoring.

    python tests/router_corpus/lab/haiku_judge.py OUT.json [split ...]

Writes every answer with its usage and wall time to OUT.json, then prints the reports and the cost.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HOOKS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugins", "joao-kit", "hooks")
sys.path.insert(0, os.path.abspath(HOOKS))
import router_eval  # noqa: E402

SYSTEM = """You label a prompt that a developer typed into an AI coding assistant, to pick the cheapest model that does it well. Reply with exactly one word.
chore: mechanical, fully specified work needing no judgment, only several edits or tool calls (renames across files, reformatting, translating text, converting or extracting data, bumping versions, listing or summarising files, moving files, rerunning a known command).
standard: ordinary well-scoped implementation (one feature or bug fix in one module, a script, a UI change, docs that need understanding the code, a localized error).
deep: needs real reasoning (root cause of a hard or intermittent bug, architecture or refactor plans across files, choosing between approaches, statistics or forecasting methodology, data leakage, security review, performance with unclear cause, the argument of a paper section).
none: just answer or act trivially (quick question, explanation, status, thanks, go-ahead, a single tiny edit, a note to remember)."""

CLAUDE = shutil.which("claude") or "claude"
FLAGS = ["--model", "haiku", "--tools", "", "--setting-sources", "", "--strict-mcp-config",
         "--exclude-dynamic-system-prompt-sections", "--output-format", "json"]


def judge(prompt):
    start = time.perf_counter()
    proc = subprocess.run([CLAUDE, "-p", "Prompt:\n" + prompt, "--system-prompt", SYSTEM, *FLAGS],
                          capture_output=True, text=True, encoding="utf-8", timeout=120, shell=False)
    wall = time.perf_counter() - start
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return {"label": "error", "wall_s": wall, "cost": 0, "usage": {}, "raw": proc.stderr[-300:]}
    word = (data.get("result") or "").strip().lower().strip(".")
    return {"label": word if word in router_eval.TIERS else "none", "raw": data.get("result"),
            "wall_s": wall, "cost": data.get("total_cost_usd") or 0, "usage": data.get("usage") or {}}


def main():
    out_path, splits = sys.argv[1], sys.argv[2:] or ["holdout", "blind2"]
    rows = [r for r in router_eval.load() if r["split"] in splits]
    cache = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {}
    todo = [r for r in rows if r["id"] not in cache]
    with ThreadPoolExecutor(4) as pool:
        for row, ans in zip(todo, pool.map(lambda r: judge(r["prompt"]), todo)):
            cache[row["id"]] = ans
            json.dump(cache, open(out_path, "w", encoding="utf-8"), indent=1)
    for split in splits:
        part = [r for r in rows if r["split"] == split]
        labels = {r["id"]: cache[r["id"]]["label"] for r in part}

        def classify(prompt, _map={r["prompt"]: labels[r["id"]] for r in part}):
            lab = _map[prompt]
            return (None if lab == "none" else lab), [lab]

        result = router_eval.evaluate(classify, part)
        print(router_eval.format_report(f"E Haiku judge on {split}", result, show_errors=True))
        missed = router_eval.failed_criteria(result)
        print("criteria: " + ("met" if not missed else "MISSED - " + "; ".join(missed)))
        answers = [cache[r["id"]] for r in part]
        tok = [sum(a["usage"].get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                   "cache_read_input_tokens", "output_tokens"))
               for a in answers]
        walls = sorted(a["wall_s"] for a in answers)
        print(f"cost ${sum(a['cost'] for a in answers):.4f} for {len(answers)} calls, "
              f"mean {sum(tok) / len(tok):.0f} tokens/call, errors {sum(a['label'] == 'error' for a in answers)}, "
              f"wall p50 {walls[len(walls) // 2]:.1f}s p95 {walls[int(0.95 * (len(walls) - 1))]:.1f}s\n")


if __name__ == "__main__":
    main()
