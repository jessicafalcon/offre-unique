"""Second, stricter judging pass on the notes written by notes_compare.py.

    python experiments/rejudge.py [--tag _v2] [--judge MODEL] [--workers 3]

For every note accepted for both the candidate and Haiku, the judge sees the pair twice, once in
each order. A side wins only if it wins in both orders; otherwise it is a tie. This removes position
bias. Verdicts and the judge's reasons are saved, so disagreements can be read.
Reads experiments/results/notes{tag}_*.json; writes experiments/results/judge{tag}.json and .md.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from _shared import RESULTS, featherless
from notes_compare import JUDGE_PROMPT, MAX_TOKENS, MODEL_OPTS

VERDICT = re.compile(r'"?meilleure"?\s*:\s*"?\s*(?:note\s*)?(A|B|[ée]gal)', re.I)
REASON = re.compile(r'"?raison"?\s*:\s*"([^"]*)', re.I)


def ask(client, judge: str, facts: dict, first: str, second: str) -> tuple[str, str, float]:
    user = f"Faits : {json.dumps(facts, ensure_ascii=False)}\n\nNote A : {first}\n\nNote B : {second}"
    r = client.chat.completions.create(model=judge, temperature=0, max_tokens=MAX_TOKENS + 3000,
                                       extra_body=MODEL_OPTS.get(judge, {}),
                                       messages=[{"role": "system", "content": JUDGE_PROMPT},
                                                 {"role": "user", "content": user}])
    txt = r.choices[0].message.content or ""
    m, why = VERDICT.search(txt), REASON.search(txt)
    v = m.group(1).upper() if m else "?"
    v = "TIE" if v.startswith(("É", "E")) else v
    return v, (why.group(1) if why else txt[-200:]), float(getattr(r.usage, "cost", 0) or 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="_v2")
    ap.add_argument("--judge", default="deepseek-ai/DeepSeek-V4.1-Flash")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    client = featherless()
    files = sorted(glob.glob(str(RESULTS / f"notes{a.tag}_*.json")))
    report, cost = {}, 0.0
    for f in files:
        name = Path(f).stem.replace(f"notes{a.tag}_", "").replace(f"notes{a.tag}", "")
        name = name.lstrip("_")
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        keys = [k for k, v in d.items() if v["verified"] and v.get("haiku")]

        def one(k):
            v = d[k]
            v1, r1, c1 = ask(client, a.judge, v["facts"], v["note"], v["haiku"])   # candidate = A
            v2, r2, c2 = ask(client, a.judge, v["facts"], v["haiku"], v["note"])   # candidate = B
            cand = {"A": "candidate", "B": "haiku", "TIE": "tie"}.get(v1, "invalid")
            cand2 = {"B": "candidate", "A": "haiku", "TIE": "tie"}.get(v2, "invalid")
            final = cand if cand == cand2 else ("invalid" if "invalid" in (cand, cand2) else "tie")
            return k, {"order1": cand, "order2": cand2, "final": final, "why1": r1, "why2": r2}, c1 + c2

        rows = {}
        with ThreadPoolExecutor(a.workers) as ex:
            for k, res, c in ex.map(one, keys):
                rows[k] = res
                cost += c
        tally = {x: sum(1 for r in rows.values() if r["final"] == x) for x in ("candidate", "haiku", "tie", "invalid")}
        bias = sum(1 for r in rows.values() if r["order1"] != r["order2"]) / max(len(rows), 1)
        report[name] = {"n": len(rows), "final": tally, "order_flips": round(bias, 3), "details": rows}
        print(f"{name}: {tally} · verdict changes with order in {100 * bias:.0f} % of pairs", flush=True)

    (RESULTS / f"judge{a.tag}.json").write_text(json.dumps({"judge": a.judge, "cost_usd": round(cost, 4), "models": report},
                                                          ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["| Modèle | Paires | Candidat préféré | Haiku préféré | Égal ou incohérent | Illisible | Verdict qui change avec l'ordre |",
             "|---|---|---|---|---|---|---|"]
    for name, r in report.items():
        t = r["final"]
        lines.append(f"| {name} | {r['n']} | {t['candidate']} | {t['haiku']} | {t['tie']} | {t['invalid']} | {100 * r['order_flips']:.0f} % |")
    lines.append(f"\nJuge : {a.judge} · coût total ${cost:.3f}")
    (RESULTS / f"judge{a.tag}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
