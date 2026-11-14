"""Experiment C: can a Featherless model replace Claude Haiku for the go / no-go notes?

    python experiments/notes_compare.py [--models a,b,c] [--judge MODEL] [--workers 2]

Rebuilds the facts of the Haiku notes (artifacts/notes_haiku.json, Jessica's backup) with her own code
(profile_of, fit_table, relevant, facts_for), then asks each candidate model to write the same notes
with the same system prompt and the same acceptance checks (explain.generate: numbers in the facts,
correct pairing of share and count, complete sentence, 2 retries).
The prompt is explain.SYSTEM as it is in src/ (Jessica's 11:30 version).
Metrics per model: share accepted, share accepted at first try, format (2 sentences, <= 45 words,
2nd sentence starts with the given recommendation, recommendation unchanged, starts with a capital
letter, no English), cost, latency, and a blind pairwise preference against Haiku by a judge model
that is not a candidate (order randomised).
Complements src/benchmark_llm.py (first try only, automatic checks): retries as in the app,
per-model settings that switch reasoning off, the truncated-start check and the judge.
Variant "<model>+fewshot": the prompt also carries 6 Haiku notes as examples; those 6 are removed
from the evaluation set of every model so the comparison stays fair.
Writes experiments/results/notes_compare.json, notes_compare.md and notes_<model>.json.
artifacts/notes.json is only read.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pyarrow.parquet as pq

from _shared import RESULTS, featherless, guard
import explain
from common import ART, CLEAN
from profiles import fit_table, load_all_scored, profile_of, relevant

DEFAULT_MODELS = "google/gemma-4-31B-it,Qwen/Qwen3.8-27B,openai/gpt-oss-120b,zai-org/GLM-5.3-Flash,zai-org/GLM-5.3"
JUDGE = "deepseek-ai/DeepSeek-V4.1-Flash"
CHECKS = ("two_sentences", "max_45_words", "starts_with_reco", "reco_unchanged", "starts_upper", "french")
ENGLISH = re.compile(r"\b(the|and|we|need|must|should|sentence|words?)\b", re.I)  # same as src/benchmark_llm.py
# Per-model request options: the settings that limited the reasoning best in a quick test
MODEL_OPTS = {
    "zai-org/GLM-5.3-Flash": {"reasoning_effort": "none"},
    "zai-org/GLM-5.3": {"reasoning_effort": "low"},
    "Qwen/Qwen3.8-27B": {"chat_template_kwargs": {"enable_thinking": False}},
    "openai/gpt-oss-120b": {"reasoning_effort": "low"},
}
PROMPT_EXTRA = ""  # set by --prompt-extra
MAX_TOKENS = 3000  # reasoning models need room before the answer; caps runaway reasoning
RECOS = ("Aller", "À étudier", "Passer")
AWARD_COLS = ["company_siren", "cpv_div", "cpv_grp", "cpv_cls", "dept", "amount_band", "categorie",
              "titulaire_nom", "date"]


def facts_by_key(keys: list[str]) -> dict[str, dict]:
    """Facts for each 'siren:code' key, rebuilt exactly as the app and explain.main() do."""
    sirens = sorted({k.split(":")[0] for k in keys})
    awards = pq.read_table(CLEAN / "awards.parquet", columns=AWARD_COLS,
                           filters=[("company_siren", "in", sirens)]).to_pandas()
    scored = load_all_scored()
    out = {}
    for s in sirens:
        prof = profile_of(awards, s)
        t = relevant(fit_table(prof, scored, awards)).sort_values("proba", ascending=False)
        for _, row in t.iterrows():
            k = f"{s}:{row.get('code')}"
            if k in keys:
                out[k] = explain.facts_for(row, prof)
    return out


def sentences(note: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-ZÀÂÉÈÊÎÔÛÇ«])", note.strip()) if s]


def format_checks(note: str, facts: dict) -> dict:
    s = sentences(note)
    reco = facts.get("recommandation", "")
    second = s[1] if len(s) > 1 else ""
    return {
        "two_sentences": len(s) == 2,
        "max_45_words": len(re.findall(r"\w+(?:['’]\w+)?", note)) <= 45,
        "starts_with_reco": second.startswith(reco),
        "reco_unchanged": reco in note and not any(r in note for r in RECOS if r != reco),
        "starts_upper": bool(note) and note[0].isupper(),
        "french": not ENGLISH.search(note),
    }


class Caller:
    """Replaces explain.complete for one model; counts calls, cost and time."""

    def __init__(self, model: str, examples: str = ""):
        self.model, self.examples = model, examples
        self.client = featherless()
        self.lock = threading.Lock()
        self.calls = self.cost = self.secs = 0.0

    def __call__(self, user: str) -> str:
        system = explain.SYSTEM + PROMPT_EXTRA + (("\n\nExemples de notes réussies (faits → note) :\n" + self.examples)
                                                  if self.examples else "")
        t = time.time()
        r = self.client.chat.completions.create(
            model=self.model, temperature=0.2, max_tokens=MAX_TOKENS, extra_body=MODEL_OPTS.get(self.model, {}),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        with self.lock:
            self.calls += 1
            self.secs += time.time() - t
            self.cost += float(getattr(r.usage, "cost", 0) or 0)
        return r.choices[0].message.content or ""


def run_model(name: str, facts: dict, examples: str, workers: int) -> dict:
    model = name.replace("+fewshot", "")
    caller = Caller(model, examples if name.endswith("+fewshot") else "")
    notes, first_try = {}, {}

    def one(k):
        counter = []
        res = _generate(facts[k], lambda u: (counter.append(1), caller(u))[1])
        return k, res, len(counter)

    with ThreadPoolExecutor(workers) as ex:
        for k, res, n_calls in ex.map(one, list(facts)):
            res["model"] = name
            notes[k] = res
            first_try[k] = res["verified"] and n_calls == 1
    return {"notes": notes, "first_try": first_try, "calls": caller.calls, "cost": caller.cost, "secs": caller.secs}


def _generate(facts: dict, complete, retries: int = 2) -> dict:
    """explain.generate() with the completion function passed in (thread-safe; same checks, same order)."""
    last = None
    for _ in range(retries + 1):
        note = complete(json.dumps(facts, ensure_ascii=False)).strip()
        note = re.sub(r"<think>.*?</think>", "", note, flags=re.S).strip()
        ok, bad = explain.numbers_ok(note, facts)
        ok = ok and explain.pairing_ok(note, facts)
        complete_note = len(note) >= 40 and note.rstrip().endswith((".", "!", "»"))
        if ok and complete_note:
            return {"note": note, "verified": True}
        last = {"note": note, "verified": False, "unsupported_numbers": sorted(bad)}
    return last


JUDGE_PROMPT = (
    "Tu évalues deux notes courtes destinées à une PME qui hésite à répondre à un appel d'offres public. "
    "Elles sont rédigées à partir des mêmes faits. Critères, dans l'ordre : 1) exactitude par rapport aux faits "
    "(aucun chiffre ou affirmation absent des faits), 2) la recommandation donnée dans les faits est reprise telle quelle, "
    "3) clarté et utilité pour décider, 4) concision (2 phrases, 45 mots maximum). "
    "Réponds uniquement par un objet JSON : {\"meilleure\": \"A\" | \"B\" | \"egal\", \"raison\": \"<une phrase>\"}."
)


def judge(facts: dict, haiku: str, cand: str, client, rng: random.Random) -> tuple[str, float]:
    swap = rng.random() < 0.5
    a, b = (cand, haiku) if swap else (haiku, cand)
    user = f"Faits : {json.dumps(facts, ensure_ascii=False)}\n\nNote A : {a}\n\nNote B : {b}"
    r = client.chat.completions.create(model=JUDGE, temperature=0, max_tokens=MAX_TOKENS, extra_body=MODEL_OPTS.get(JUDGE, {}),
                                       messages=[{"role": "system", "content": JUDGE_PROMPT},
                                                 {"role": "user", "content": user}])
    txt = r.choices[0].message.content or ""
    m = re.search(r'"meilleure"\s*:\s*"(A|B|egal|égal)"', txt)
    v = m.group(1) if m else "?"
    cost = float(getattr(r.usage, "cost", 0) or 0)
    if v in ("egal", "égal"):
        return "tie", cost
    if v == "?":
        return "invalid", cost
    cand_is = "A" if swap else "B"
    return ("candidate" if v == cand_is else "haiku"), cost


def main():
    global JUDGE, PROMPT_EXTRA
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--judge", default=JUDGE)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0, help="evaluate only the first N notes (smoke test)")
    ap.add_argument("--tag", default="", help="suffix for the result files")
    ap.add_argument("--prompt-extra", default="", help="sentence appended to explain.SYSTEM (prompt variant test)")
    a = ap.parse_args()
    JUDGE = a.judge
    PROMPT_EXTRA = (" " + a.prompt_extra) if a.prompt_extra else ""

    haiku = json.loads((ART / "notes_haiku.json").read_text(encoding="utf-8"))
    facts = facts_by_key(list(haiku))
    print(f"rebuilt facts for {len(facts)} of {len(haiku)} cached Haiku notes · mem {guard('facts'):.2f} GB", flush=True)

    # 6 few-shot examples: 2 per recommendation when available, then removed from evaluation
    rng = random.Random(0)
    by_reco = {r: [k for k in facts if facts[k].get("recommandation") == r and haiku[k].get("verified")] for r in RECOS}
    shots = [k for r in RECOS for k in rng.sample(by_reco[r], min(2, len(by_reco[r])))]
    examples = "\n".join(f"{json.dumps(facts[k], ensure_ascii=False)}\n→ {haiku[k]['note']}" for k in shots)
    evalset = {k: v for k, v in facts.items() if k not in shots}
    if a.limit:
        evalset = dict(list(evalset.items())[:a.limit])
    counts = {r: sum(1 for f in evalset.values() if f.get("recommandation") == r) for r in RECOS}
    print(f"evaluation set: {len(evalset)} notes {counts}", flush=True)

    summary = {}
    ref = {"accepted": sum(haiku[k]["verified"] for k in evalset) / len(evalset)}
    ref.update({c: sum(format_checks(haiku[k]["note"], evalset[k])[c] for k in evalset) / len(evalset)
                for c in CHECKS})
    summary["claude-haiku-5-5 (référence, notes existantes)"] = ref
    jclient = featherless()

    for name in [m.strip() for m in a.models.split(",") if m.strip()]:
        t = time.time()
        r = run_model(name, evalset, examples, a.workers)
        notes = r["notes"]
        n = len(evalset)
        s = {"accepted": sum(v["verified"] for v in notes.values()) / n,
             "accepted_first_try": sum(r["first_try"].values()) / n}
        s.update({c: sum(format_checks(notes[k]["note"], evalset[k])[c] for k in evalset) / n
                  for c in CHECKS})
        s.update({"cost_usd": round(r["cost"], 4), "calls": int(r["calls"]),
                  "sec_per_call": round(r["secs"] / max(r["calls"], 1), 1), "wall_min": round((time.time() - t) / 60, 1)})
        # blind pairwise judgement against Haiku, on notes both accepted
        votes, jcost = {"candidate": 0, "haiku": 0, "tie": 0, "invalid": 0}, 0.0
        jr = random.Random(1)
        for k in evalset:
            if notes[k]["verified"] and haiku[k]["verified"]:
                v, c = judge(evalset[k], haiku[k]["note"], notes[k]["note"], jclient, jr)
                votes[v] += 1
                jcost += c
        s["judge_vs_haiku"] = votes
        s["judge_cost_usd"] = round(jcost, 4)
        summary[name] = s
        (RESULTS / f"notes{a.tag}_{name.replace('/', '_').replace('+', '_')}.json").write_text(
            json.dumps({k: {**notes[k], "facts": evalset[k], "haiku": haiku[k]["note"]} for k in evalset},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{name}: {json.dumps(s, ensure_ascii=False)} · mem {guard(name):.2f} GB", flush=True)

    (RESULTS / f"notes_compare{a.tag}.json").write_text(json.dumps({"n_eval": len(evalset), "few_shot_keys": shots,
                                                            "judge": JUDGE, "summary": summary},
                                                           ensure_ascii=False, indent=2), encoding="utf-8")
    pct = lambda x: f"{100 * x:.0f} %"
    lines = ["| Modèle | Acceptées | Au 1er essai | 2 phrases | ≤ 45 mots | Commence par la reco | Reco inchangée "
             "| Début intact | Sans anglais | Juge : préfère le candidat / Haiku / égal | Coût notes | s / appel |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, s in summary.items():
        j = s.get("judge_vs_haiku")
        votes = f"{j['candidate']} / {j['haiku']} / {j['tie']}" if j else "–"
        first = pct(s["accepted_first_try"]) if "accepted_first_try" in s else "–"
        cost = f"${s['cost_usd']}" if "cost_usd" in s else "–"
        lines.append(f"| {name} | {pct(s['accepted'])} | {first} | {pct(s['two_sentences'])} | {pct(s['max_45_words'])} "
                     f"| {pct(s['starts_with_reco'])} | {pct(s['reco_unchanged'])} | {pct(s['starts_upper'])} "
                     f"| {pct(s['french'])} | {votes} | {cost} "
                     f"| {s.get('sec_per_call', '–')} |")
    (RESULTS / f"notes_compare{a.tag}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
