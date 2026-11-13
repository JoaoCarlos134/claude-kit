"""Lab variant D: multinomial naive Bayes (standard library only) trained on the labeled corpus.

Settings fixed before any score was seen: lowercase, accents stripped, word unigrams + bigrams, Laplace
alpha 1, uniform class prior (the corpus is balanced by construction, real traffic is not). Trains on the
`tune` split plus `blind` (blind was spent tuning v2, so v2 and D see the same data); scored on `holdout`
and `blind2`.

    python tests/router_corpus/lab/naive_bayes.py
"""

import math
import os
import re
import sys
import unicodedata
from collections import Counter

HOOKS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugins", "joao-kit", "hooks")
sys.path.insert(0, os.path.abspath(HOOKS))
import router_eval  # noqa: E402

TIERS = router_eval.TIERS
TRAIN_SPLITS = ("tune", "blind")


def tokens(text):
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    words = re.findall(r"[a-z0-9_]+", text)
    return words + [a + " " + b for a, b in zip(words, words[1:])]


class NaiveBayes:
    def __init__(self, rows, alpha=1.0):
        self.counts = {t: Counter() for t in TIERS}
        for row in rows:
            self.counts[row["expect"]].update(tokens(row["prompt"]))
        self.vocab = set().union(*self.counts.values())
        self.totals = {t: sum(c.values()) for t, c in self.counts.items()}
        self.alpha = alpha

    def scores(self, prompt):
        out = {}
        v = len(self.vocab)
        for t in TIERS:
            denom = self.totals[t] + self.alpha * v
            out[t] = sum(math.log((self.counts[t][w] + self.alpha) / denom)
                         for w in tokens(prompt) if w in self.vocab)
        return out

    def classify(self, prompt):
        s = self.scores(prompt)
        best = max(s, key=s.get)
        return (None if best == "none" else best), [best]


def main():
    rows = router_eval.load()
    model = NaiveBayes([r for r in rows if r["split"] in TRAIN_SPLITS])
    for split in ("holdout", "blind2"):
        part = [r for r in rows if r["split"] == split]
        result = router_eval.evaluate(model.classify, part)
        print(router_eval.format_report(f"D naive Bayes on {split}", result))
        missed = router_eval.failed_criteria(result)
        print("criteria: " + ("met" if not missed else "MISSED - " + "; ".join(missed)) + "\n")


if __name__ == "__main__":
    main()
