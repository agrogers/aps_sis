"""Pairwise comparison test: can the model rank answers more reliably than it scores them?

Every pair of essays is compared in both orders (A/B and B/A) and repeated --reps times.
Each call returns "better", "same" or "worse" for Answer A relative to Answer B.

Reported:
  - agreement with the official marks (official tie = "same"),
  - order consistency (A/B and B/A give opposite verdicts),
  - repeat consistency (the same ordered pair gives the same verdict),
  - a ranking by win rate,
  - a leave-one-out placement: each essay's mark is estimated only from its comparisons
    with the other essays and their official marks.

Usage (key is read from the OPENROUTER_API_KEY environment variable):
  python compare_openrouter.py --effort medium --reps 2 --out compare_v1_medium.json
"""
import argparse
import concurrent.futures as cf
import hashlib
import itertools
import json
import os
import sys
from pathlib import Path

from score_openrouter import DEFAULT_PROJECT, MODEL, load_essays, pair_agreement, parse_json, post_chat

VERDICT = {"better": 1, "same": 0, "worse": -1}
SAME_BAND = 1.0  # "same" means within this many marks, as stated in the comparison prompt


def compare_one(system, a, b, rep, essays, args, key):
    rec = {"rep": rep, "a": a, "b": b, "verdict": None, "error": None}
    user = (
        f"<answer_a>\n{essays[a]}\n</answer_a>\n\n<answer_b>\n{essays[b]}\n</answer_b>\n\n"
        "Compare Answer A with Answer B. Return a valid json object only."
    )
    try:
        resp = post_chat(system, user, args, key)
        content = resp["choices"][0]["message"]["content"]
        rec["raw"] = content
        obj = parse_json(content)
        verdict = str(obj.get("comparison", "")).strip().lower()
        if verdict not in VERDICT:
            raise ValueError(f"unexpected comparison value: {verdict!r}")
        rec.update(verdict=verdict, reason=obj.get("reason"))
        usage = resp.get("usage", {})
        details = usage.get("prompt_tokens_details") or {}
        rec.update(
            cost=usage.get("cost"),
            prompt_tokens=usage.get("prompt_tokens"),
            cached_tokens=details.get("cached_tokens") or 0,
            completion_tokens=usage.get("completion_tokens"),
            reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            provider=resp.get("provider"),
        )
    except Exception as e:  # keep the batch going; the failure is reported
        rec["error"] = str(e)[:500]
    return rec


def sign(x):
    return (x > 0) - (x < 0)


def place(votes):
    """Estimate a mark from (anchor_mark, vote) pairs, vote = +1 better / 0 same / -1 worse.

    Minimises a hinge loss: "better" wants mark >= anchor + 1, "worse" wants mark <= anchor - 1,
    "same" wants |mark - anchor| <= 1. Returns the midpoint of the best-scoring marks; when that
    range is open-ended (beats or loses to every anchor) it returns the end next to the anchors.
    """
    candidates = [m / 2 for m in range(0, 61)]
    def loss(m):
        total = 0.0
        for anchor, v in votes:
            if v > 0:
                total += max(0.0, anchor + SAME_BAND - m)
            elif v < 0:
                total += max(0.0, m - (anchor - SAME_BAND))
            else:
                total += max(0.0, abs(m - anchor) - SAME_BAND)
        return total
    losses = {m: loss(m) for m in candidates}
    best = min(losses.values())
    tied = [m for m, l in losses.items() if l - best < 1e-9]
    lo, hi = min(tied), max(tied)
    if lo == candidates[0] and hi < candidates[-1]:
        return hi
    if hi == candidates[-1] and lo > candidates[0]:
        return lo
    return (lo + hi) / 2


def report(results, ids, official):
    ok = [r for r in results if r["verdict"]]
    errors = [r for r in results if r["error"]]

    # Agreement with the official marks, per call.
    hits = sum(VERDICT[r["verdict"]] == sign(official[r["a"]] - official[r["b"]]) for r in ok)
    strict = [r for r in ok if official[r["a"]] != official[r["b"]]]
    strict_hits = sum(VERDICT[r["verdict"]] == sign(official[r["a"]] - official[r["b"]]) for r in strict)
    direction_ok = sum(VERDICT[r["verdict"]] != -sign(official[r["a"]] - official[r["b"]]) for r in strict)
    print(f"Calls: {len(results)}   errors: {len(errors)}")
    print(f"Verdict matches official exactly: {hits}/{len(ok)} ({hits / max(len(ok), 1):.0%})")
    print(f"  on pairs with different official marks: {strict_hits}/{len(strict)} exact, "
          f"{direction_ok}/{len(strict)} not reversed (better/worse not flipped)")

    # Order consistency: (a,b) and (b,a) in the same rep should be opposite verdicts.
    by_key = {(r["rep"], r["a"], r["b"]): VERDICT[r["verdict"]] for r in ok}
    pairs = [(rep, a, b) for (rep, a, b) in by_key if a < b and (rep, b, a) in by_key]
    order_ok = sum(by_key[(rep, a, b)] == -by_key[(rep, b, a)] for rep, a, b in pairs)
    first_bias = sum(v for (rep, a, b), v in by_key.items()) / max(len(by_key), 1)
    print(f"Order consistency (A/B vs B/A opposite): {order_ok}/{len(pairs)} ({order_ok / max(len(pairs), 1):.0%})"
          f"   mean verdict for Answer A: {first_bias:+.2f} (0 = no position bias)")

    # Repeat consistency: same ordered pair across reps.
    reps = sorted({r["rep"] for r in ok})
    same_rep, total_rep = 0, 0
    for a, b in itertools.permutations(ids, 2):
        vals = [by_key[(rep, a, b)] for rep in reps if (rep, a, b) in by_key]
        if len(vals) > 1:
            total_rep += 1
            same_rep += len(set(vals)) == 1
    if total_rep:
        print(f"Repeat consistency (same ordered pair, all reps agree): {same_rep}/{total_rep} ({same_rep / total_rep:.0%})")

    # Ranking by win rate and leave-one-out placement on the mark scale.
    wins, votes = {e: [] for e in ids}, {e: [] for e in ids}
    for r in ok:
        v = VERDICT[r["verdict"]]
        wins[r["a"]].append((v + 1) / 2)
        wins[r["b"]].append((1 - v) / 2)
        votes[r["a"]].append((official[r["b"]], v))
        votes[r["b"]].append((official[r["a"]], -v))
    rate = {e: sum(w) / len(w) for e, w in wins.items() if w}
    placed = {e: place(v) for e, v in votes.items() if v}
    print(f"\n{'essay':6}{'official':>10}{'win rate':>10}{'placed':>9}{'diff':>7}")
    for e in sorted(ids, key=lambda x: -rate.get(x, 0)):
        if e in placed:
            print(f"{e:6}{official[e]:>10}{rate[e]:>10.2f}{placed[e]:>9.1f}{placed[e] - official[e]:>+7.1f}")
    good, total = pair_agreement(rate, official)
    print(f"Ranking order agreement (win rate vs official): {good:g}/{total}")
    if placed:
        mae = sum(abs(placed[e] - official[e]) for e in placed) / len(placed)
        print(f"Leave-one-out placement mean abs error: {mae:.2f}")

    cost = sum(r.get("cost") or 0 for r in ok)
    cache_hits = sum(1 for r in ok if r.get("cached_tokens"))
    providers = sorted({str(r.get("provider")) for r in ok if r.get("provider")})
    print(f"Cost: ${cost:.5f}   Cache: {cache_hits}/{len(ok)} calls read cache   Providers: {', '.join(providers) or '-'}")
    for r in errors:
        print(f"  error {r['a']} vs {r['b']} rep {r['rep']}: {r['error']}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--project", default=str(DEFAULT_PROJECT), help="question folder holding essays_blind.txt and official_marks.json")
    p.add_argument("--system", default="rubrics/compare_v1_system.txt", help="comparison system message, relative to --project unless absolute")
    p.add_argument("--model", default=MODEL, help="OpenRouter model slug")
    p.add_argument("--effort", default="medium", choices=["minimal", "low", "medium", "high", "xhigh", "none"])
    p.add_argument("--temperature", type=float, default=0.05)
    p.add_argument("--max-tokens", type=int, default=9200)
    p.add_argument("--reps", type=int, default=2, help="repeats of every ordered pair")
    p.add_argument("--essays", nargs="*", help="subset, e.g. E1 E2 E3")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--no-cache", dest="cache", action="store_false", help="disable prompt caching of the system message")
    p.add_argument("--out", required=True, help="output JSON, relative to <project>\\results unless absolute")
    args = p.parse_args()

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("Set OPENROUTER_API_KEY first.")

    project = Path(args.project)
    system_path = Path(args.system) if Path(args.system).is_absolute() else project / args.system
    out_path = Path(args.out) if Path(args.out).is_absolute() else project / "results" / args.out
    official = {k: int(v) for k, v in json.loads((project / "official_marks.json").read_text(encoding="utf-8")).items()}
    system = system_path.read_text(encoding="utf-8")
    essays = load_essays(project / "essays_blind.txt")
    ids = args.essays or list(official)

    jobs = [(rep, a, b) for rep in range(1, args.reps + 1) for a, b in itertools.permutations(ids, 2)]
    results = []
    if args.cache and jobs:
        # Parallel calls fired before the first cache write would all miss, so warm it first.
        rep, a, b = jobs.pop(0)
        results.append(compare_one(system, a, b, rep, essays, args, key))
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(compare_one, system, a, b, rep, essays, args, key) for rep, a, b in jobs]
        for f in cf.as_completed(futs):
            results.append(f.result())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"model": args.model, "system": system_path.name, "config": {k: v for k, v in vars(args).items() if k != "out"}, "results": results}, indent=2),
        encoding="utf-8",
    )
    print(f"Model {args.model}, effort {args.effort}, temperature {args.temperature}, system {system_path.name}")
    report(results, ids, official)
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
