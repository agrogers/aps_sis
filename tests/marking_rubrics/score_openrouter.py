"""Score blind marking samples through OpenRouter, mirroring the production request.

Each question lives in its own folder under marking_rubrics, for example
english_language_b\\q10_story_writing, containing:
  essays_blind.txt     sections headed "=== E1 ===" etc. (unmarked)
  official_marks.json  {"E1": 16, ...}
  rubrics\\             system messages to test
  results\\             output JSON files

Usage (key is read from the OPENROUTER_API_KEY environment variable):
  python score_openrouter.py --effort low --runs 3 --out results_low.json
Paths for --system and --out are relative to the project folder unless absolute.
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from text_stats import statistics_block

HERE = Path(__file__).parent
DEFAULT_PROJECT = HERE / "english_language_b" / "q10_story_writing"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-haiku-5.5"
RETRY_CODES = {408, 429, 500, 502, 503, 504}


def load_essays(path):
    essays, current = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^=== (E\d+) ===\s*$", line)
        if m:
            current = m.group(1)
            essays[current] = []
        elif current:
            essays[current].append(line)
    return {k: "\n".join(v).strip() for k, v in essays.items()}


def call_model(system, essay, args, key, extra=""):
    user = f"<student_answer>\n{essay}\n</student_answer>\n\n"
    if extra:
        user += extra + "\n\n"
    return post_chat(system, user + "Return a valid json object only.", args, key)


def post_chat(system, user, args, key):
    """Send one system + user request; the stable system message comes first so it can be cached."""
    system_content = system
    if args.cache:
        # Anthropic caching is opt-in: the breakpoint caches the whole stable system prefix.
        system_content = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    body = {
        "model": args.model,
        "temperature": args.temperature,
        "max_completion_tokens": args.max_tokens,
        "reasoning": {"effort": args.effort, "enabled": True, "exclude": False},
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user},
        ],
    }
    if args.cache:
        # Sticky routing keeps calls with the same system prefix on the provider that holds its cache.
        cache_key = "rubric-" + hashlib.sha256(system.encode("utf-8")).hexdigest()[:32]
        body["session_id"] = cache_key
        body["prompt_cache_key"] = cache_key
    data = json.dumps(body).encode("utf-8")
    last_err = None
    for attempt in range(4):
        req = urllib.request.Request(
            API_URL,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "X-Title": "ar_phonics Q10 rubric test",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
            if e.code not in RETRY_CODES:
                break
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = str(e)
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(last_err)


def parse_json(text):
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    return json.loads(text)


def score_one(system, essay_id, essay, run, args, key, extra=""):
    rec = {"run": run, "essay": essay_id, "score": None, "error": None}
    try:
        resp = call_model(system, essay, args, key, extra)
        content = resp["choices"][0]["message"]["content"]
        rec["raw"] = content
        obj = parse_json(content)
        rec.update(score=obj.get("score"), score_comment=obj.get("score_comment"), summary=obj.get("summary"))
        usage = resp.get("usage", {})
        prompt_details = usage.get("prompt_tokens_details") or {}
        rec.update(
            cost=usage.get("cost"),
            prompt_tokens=usage.get("prompt_tokens"),
            cached_tokens=prompt_details.get("cached_tokens") or 0,
            cache_write_tokens=prompt_details.get("cache_write_tokens") or 0,
            cache_discount=usage.get("cache_discount"),
            completion_tokens=usage.get("completion_tokens"),
            reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            provider=resp.get("provider"),
        )
    except Exception as e:  # keep the batch going; the failure is reported
        rec["error"] = str(e)[:500]
    return rec


def rubric_max_mark(system):
    m = re.search(r"<maximum_mark>\s*([\d.]+)\s*</maximum_mark>", system)
    if not m:
        sys.exit("System message has no <maximum_mark> tag; the score table needs it to label marks.")
    return float(m.group(1))


def stated_total(rec):
    m = re.search(r"TOTAL[^\n\d]*(\d+)", rec.get("score_comment") or "")
    return int(m.group(1)) if m else None


def pair_agreement(means, official):
    ids = list(means)
    good, total = 0.0, 0
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            o = official[a] - official[b]
            if o == 0:
                continue
            m = means[a] - means[b]
            total += 1
            if m == 0:
                good += 0.5
            elif (m > 0) == (o > 0):
                good += 1
    return good, total


def report(results, ids, runs, official, max_mark):
    unit = f"/{max_mark:g}"
    header = f"{'essay':6}{'official':>10}" + "".join(f"{'run' + str(r):>10}" for r in range(1, runs + 1))
    print(header + f"{'mean':>10}{'diff':>7}")
    means, run_errs = {}, {r: [] for r in range(1, runs + 1)}
    for eid in ids:
        row = [x for x in sorted(results, key=lambda x: x["run"]) if x["essay"] == eid]
        cells, vals = [], []
        for x in row:
            s = x["score"]
            cells.append(f"{'ERR' if s is None else str(s) + unit:>10}")
            if isinstance(s, (int, float)):
                vals.append(s)
                run_errs[x["run"]].append(abs(s - official[eid]))
        mean = sum(vals) / len(vals) if vals else None
        if mean is not None:
            means[eid] = mean
        mean_s = f"{mean:.1f}{unit}" if mean is not None else "-"
        diff_s = f"{mean - official[eid]:+7.1f}" if mean is not None else f"{'-':>7}"
        print(f"{eid:6}{str(official[eid]) + unit:>10}" + "".join(cells) + f"{mean_s:>10}" + diff_s)
    per_run_mae = [sum(e) / len(e) for e in run_errs.values() if e]
    if per_run_mae:
        print(f"Mean abs error per run: {', '.join(f'{m:.2f}' for m in per_run_mae)}  (avg {sum(per_run_mae) / len(per_run_mae):.2f})")
    good, total = pair_agreement(means, official)
    print(f"Pairwise order agreement (on means): {good:g}/{total}")
    errors = [x for x in results if x["error"]]
    no_total = [x for x in results if stated_total(x) is None]
    mismatches = [x for x in results if stated_total(x) is not None and stated_total(x) != x["score"]]
    print(f"Errors: {len(errors)}   TOTAL missing: {len(no_total)}   TOTAL vs score mismatches: {len(mismatches)}")
    for x in errors:
        print(f"  error {x['essay']} run {x['run']}: {x['error']}")
    for x in no_total:
        print(f"  no TOTAL in score_comment: {x['essay']} run {x['run']}")
    cost = sum(x.get("cost") or 0 for x in results)
    providers = sorted({str(x.get("provider")) for x in results if x.get("provider")})
    print(f"Cost: ${cost:.5f}   Providers: {', '.join(providers) or '-'}")
    ok = [x for x in results if not x["error"]]
    hits = sum(1 for x in ok if x.get("cached_tokens"))
    print(
        f"Cache: {hits}/{len(ok)} calls read cache   "
        f"read tokens {sum(x.get('cached_tokens') or 0 for x in ok)}   "
        f"write tokens {sum(x.get('cache_write_tokens') or 0 for x in ok)}   "
        f"prompt tokens {sum(x.get('prompt_tokens') or 0 for x in ok)}"
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--project", default=str(DEFAULT_PROJECT), help="question folder holding essays_blind.txt and official_marks.json")
    p.add_argument("--system", default="rubrics/request_v10_system.txt", help="system message file, relative to --project unless absolute")
    p.add_argument("--model", default=MODEL, help="OpenRouter model slug")
    p.add_argument("--effort", default="low", choices=["minimal", "low", "medium", "high", "xhigh", "none"])
    p.add_argument("--temperature", type=float, default=0.05)
    p.add_argument("--max-tokens", type=int, default=9200)
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--essays", nargs="*", help="subset, e.g. E4 E5")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--no-cache", dest="cache", action="store_false", help="disable prompt caching of the system message")
    p.add_argument("--stats", action="store_true", help="append measured text statistics, compared with the other marked answers")
    p.add_argument("--anchors", nargs="*", help="standardisation scripts appended to the system message; each argument is a "
                   "comma-separated preference list, e.g. E6,E1 E2,E8 E7,E5 (first entry that is not the answer being marked)")
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
    max_mark = rubric_max_mark(system)
    essays = load_essays(project / "essays_blind.txt")
    ids = args.essays or list(official)
    jobs = [(run, eid) for run in range(1, args.runs + 1) for eid in ids]

    # Anchors and statistics are leave-one-out: an answer never sees its own official mark.
    def system_for(eid):
        if not args.anchors:
            return system
        chosen = [next(a for a in group.split(",") if a != eid) for group in args.anchors]
        scripts = "\n\n".join(
            f'<script mark="{official[a]}/{max_mark:g}">\n{essays[a]}\n</script>'
            for a in sorted(chosen, key=lambda a: official[a])
        )
        return (
            f"{system}\n\n<standardisation_scripts>\n"
            "These answers to the same task were marked by the senior examiner. Use them to calibrate your standard: "
            "an answer of similar quality should receive a similar total, and your item marks should produce totals "
            "consistent with these marks. Never mention these scripts in your output.\n\n"
            f"{scripts}\n</standardisation_scripts>"
        )

    def extra_for(eid):
        if not args.stats:
            return ""
        exemplars = {}
        for other in official:
            if other != eid and other in essays:
                exemplars.setdefault(official[other], []).append(essays[other])
        return statistics_block(essays[eid], exemplars)

    def submit(run, eid):
        return score_one(system_for(eid), eid, essays[eid], run, args, key, extra_for(eid))

    results = []
    if args.cache:
        # Parallel calls fired before a cache write would all miss, so warm each distinct system prefix first.
        warmed = set()
        for job in list(jobs):
            prefix = system_for(job[1])
            if prefix not in warmed:
                warmed.add(prefix)
                jobs.remove(job)
                results.append(submit(*job))
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(submit, run, eid) for run, eid in jobs]
        for f in cf.as_completed(futs):
            results.append(f.result())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"model": args.model, "system": str(system_path.name), "config": {k: v for k, v in vars(args).items() if k != "out"}, "results": results}, indent=2),
        encoding="utf-8",
    )
    print(f"Model {args.model}, effort {args.effort}, temperature {args.temperature}, system {system_path.name}")
    report(results, ids, args.runs, official, max_mark)
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
