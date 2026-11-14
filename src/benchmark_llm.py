"""Which LLM writes the go / no-go notes best? Same facts, same prompt, one attempt each, automatic checks only.

    python src/benchmark_llm.py                 # 40 tenders of DEMO_SIREN, 4 models
    python src/benchmark_llm.py --n 10          # quicker

Checks (the same guards the app uses, plus format):
- chiffres   : every number in the note appears in the facts (numbers_ok)
- dénominateur : no "X % des N" with the wrong N (pairing_ok)
- verdict    : sentence 2 starts with the rule's recommendation (Aller / À étudier / Passer)
- format     : exactly 2 sentences, at most 45 words, ends with a full stop
- français   : no English reasoning leaked into the note
No retries here (the app retries up to twice), so this measures first-try reliability.
Writes artifacts/llm_benchmark.json (summary) and artifacts/llm_benchmark_outputs.json (every note).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from common import ART, CLEAN
from explain import complete_with, facts_for, numbers_ok, pairing_ok

MODELS = [  # (label, provider, model id, parallel requests)
    ("Claude Haiku 5.5 (Anthropic)", "anthropic", "claude-haiku-5-5", 4),
    ("Gemma 4 31B (Featherless, open-weight)", "featherless", "google/gemma-4-31B-it", 2),
    ("gpt-oss 120B (Featherless, open-weight)", "featherless", "openai/gpt-oss-120b", 2),
    ("Qwen 3.8 27B (Featherless, open-weight)", "featherless", "Qwen/Qwen3.8-27B", 2),
    ("GLM 5.3 (Featherless, open-weight)", "featherless", "zai-org/GLM-5.3", 2),
    ("GLM 5.3 Flash (Featherless, open-weight)", "featherless", "zai-org/GLM-5.3-Flash", 2),
    ("Mistral Large 2411 (Featherless, open-weight)", "featherless", "mistralai/Mistral-Large-Instruct-2411", 2),
    ("Mistral Small 3.1 24B (Featherless, open-weight)", "featherless", "mistralai/Mistral-Small-3.1-24B-Instruct-2503", 2),
]
ENGLISH = re.compile(r"\b(the|and|we|need|must|should|sentence|words?)\b", re.I)


def checks(note: str, facts: dict) -> dict:
    sents = [x for x in re.split(r"(?<=[.!?])\s+", note.strip()) if x]
    reco = facts["recommandation"]
    c = {
        "chiffres": numbers_ok(note, facts)[0],
        "denominateur": pairing_ok(note, facts),
        "verdict": len(sents) >= 2 and sents[1].startswith(reco),
        "format": len(sents) == 2 and len(note.split()) <= 45 and note.rstrip().endswith("."),
        "francais": not ENGLISH.search(note),
    }
    c["tout"] = bool(note) and all(c.values())
    return c


def one(provider: str, model: str, facts: dict) -> dict:
    t0, err, note, usage = time.time(), None, "", {}
    for attempt in range(4):
        try:
            note, usage = complete_with(provider, model, json.dumps(facts, ensure_ascii=False),
                                        max_tokens=None if provider == "anthropic" else 1500)
            err = None
            break
        except Exception as e:  # rate limit / timeout: back off, then record the error
            err = f"{e.__class__.__name__}: {str(e)[:120]}"
            if "429" in str(e) or "rate" in str(e).lower():
                time.sleep(5 * (attempt + 1))
                continue
            break
    note = re.sub(r"<think>.*?</think>", "", note or "", flags=re.S).strip()
    return {"note": note, "error": err, "seconds": round(time.time() - t0, 1), "usage": usage,
            "checks": checks(note, facts) if not err else {k: False for k in
                                                          ("chiffres", "denominateur", "verdict", "format", "francais", "tout")}}


def run_model(label, provider, model, workers, facts_list):
    t0 = time.time()
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda f: one(provider, model, f), facts_list))
    ok = [r for r in res if not r["error"]]
    summ = {"provider": provider, "model": model, "n": len(res), "errors": len(res) - len(ok),
            "pass": {k: sum(r["checks"][k] for r in res) for k in ("tout", "chiffres", "denominateur", "verdict", "format", "francais")},
            "median_seconds": statistics.median([r["seconds"] for r in ok]) if ok else None,
            "mean_out_tokens": round(statistics.mean([r["usage"].get("out") or 0 for r in ok]), 1) if ok else None,
            "mean_in_tokens": round(statistics.mean([r["usage"].get("in") or 0 for r in ok]), 1) if ok else None,
            "wall_seconds": round(time.time() - t0)}
    print(f"{label:<42} all checks {summ['pass']['tout']:>2}/{len(res)} | " +
          " ".join(f"{k} {v}" for k, v in summ["pass"].items() if k != "tout") +
          f" | errors {summ['errors']} | median {summ['median_seconds']}s", flush=True)
    return label, summ, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--siren", default=os.environ.get("DEMO_SIREN"))
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--only", nargs="*", help="model ids to run; results are merged into the existing files")
    a = ap.parse_args()
    from profiles import fit_table, load_all_scored, profile_of, relevant
    awards = pd.read_parquet(CLEAN / "awards.parquet")
    prof = profile_of(awards, a.siren)
    t = relevant(fit_table(prof, load_all_scored(), awards)).sort_values("proba", ascending=False).head(a.n)
    facts_list = [facts_for(r, prof) for _, r in t.iterrows()]
    codes = [str(c) for c in t["code"]]
    print(f"{len(facts_list)} tenders of {prof['name']}; verdicts: "
          f"{pd.Series([f['recommandation'] for f in facts_list]).value_counts().to_dict()}", flush=True)

    # Anthropic in parallel with the Featherless models, which run one after the other (concurrency limits)
    models = [m for m in MODELS if not a.only or m[2] in a.only]
    with ThreadPoolExecutor(2) as ex:
        fut_a = ex.submit(lambda: [run_model(*m, facts_list) for m in models if m[1] == "anthropic"])
        fut_f = ex.submit(lambda: [run_model(*m, facts_list) for m in models if m[1] == "featherless"])
        results = fut_a.result() + fut_f.result()

    order = [m[0] for m in MODELS]
    results.sort(key=lambda x: order.index(x[0]))
    summary = {"date": pd.Timestamp.now().isoformat(timespec="minutes"), "company": prof["name"], "n": len(facts_list),
               "protocol": "mêmes faits, même consigne, une seule tentative par note, contrôles automatiques",
               "models": {lab: s for lab, s, _ in results}}
    outputs = {lab: [{"code": c, "verdict_attendu": f["recommandation"], **r} for c, f, r in zip(codes, facts_list, res)]
               for lab, _, res in results}
    if a.only:  # merge with earlier runs (same tenders, same prompt)
        old = json.loads((ART / "llm_benchmark.json").read_text())
        summary = {**old, "models": {**old["models"], **summary["models"]}}
        outputs = {**json.loads((ART / "llm_benchmark_outputs.json").read_text()), **outputs}
    summary["models"] = {lab: summary["models"][lab] for lab in order if lab in summary["models"]}
    (ART / "llm_benchmark.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    (ART / "llm_benchmark_outputs.json").write_text(json.dumps(outputs, ensure_ascii=False, indent=1))
    print(f"saved {ART / 'llm_benchmark.json'}")


if __name__ == "__main__":
    main()
