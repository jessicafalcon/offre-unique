"""Go / no-go notes, with a check that every number comes from the facts.

    python src/explain.py --siren 412345678 --top 10     # pre-generate and cache for the demo
    python src/explain.py --test                          # one call to check key + model

LLM_PROVIDER in .env picks the backend: "anthropic" (Claude API) or "featherless".
The model computes everything; the LLM only rewrites the computed facts in plain French.
Cache: artifacts/notes.json, keyed by "<siren>:<purchase code>".
"""
from __future__ import annotations

import argparse
import json
import os
import re

import pandas as pd

from common import ART, CLEAN

CACHE = ART / "notes.json"
PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()
MODEL = (os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5") if PROVIDER == "anthropic"
         else os.environ.get("FEATHERLESS_MODEL", "Qwen/Qwen3-32B"))

SYSTEM = (
    "Tu aides une PME à décider si elle répond à un appel d'offres public. "
    "Tu reçois des faits calculés à partir de données publiques. "
    "Point de vue de l'entreprise : une forte probabilité qu'une seule offre soit déposée est une OPPORTUNITÉ "
    "(peu ou pas de concurrents), jamais un risque ni un motif de prudence. "
    "Écris exactement 2 phrases complètes, 45 mots maximum au total : "
    "1) le constat (probabilité d'offre unique comparée à la moyenne, adéquation avec l'entreprise, "
    "historique de l'acheteur s'il existe) ; "
    "2) la recommandation donnée dans le champ « recommandation » : commence la phrase par exactement ce mot "
    "(« Aller », « À étudier » ou « Passer »), puis donne sa raison avec le champ « raison ». "
    "Ne change jamais la recommandation. "
    "Dans la phrase 1, donne toujours le pourcentage de probabilité d'offre unique ET la moyenne en pourcentage, "
    "puis le nombre de contrats similaires gagnés par l'entreprise. "
    "Écris « Aller, car », « Passer, car » ou « À étudier, car », avec la virgule. "
    "Utilise UNIQUEMENT les chiffres présents dans les faits, sans en calculer de nouveaux. "
    "La part de marchés avec une seule offre se rapporte aux marchés dont le nombre d'offres est connu, "
    "pas à tous les marchés comparables : ne rapporte jamais ce pourcentage au nombre total de marchés. "
    "N'explique pas le fonctionnement du modèle. Pas de titre, pas de liste. Ton mesuré. "
    "Ne qualifie jamais un acheteur ou un titulaire de suspect. Termine par un point."
)


def _avg_rate() -> float | None:
    p = ART / "metrics.json"
    return json.loads(p.read_text()).get("test_single_bid_rate") if p.exists() else None


def recommend(proba: float, avg: float | None, n_dept: int, hist_single: float | None,
              is_incumbent: bool = False, rival_streak: int = 0) -> tuple[str, str]:
    """Rule-based go / no-go, so the recommendation is reproducible and not left to the LLM."""
    ratio = proba / avg if avg else 1.0
    local = n_dept >= 1
    buyer_ok = hist_single is None or hist_single >= 0.30
    if is_incumbent:
        return "Aller", "l'entreprise est le titulaire sortant : un renouvellement à défendre"
    # Thresholds on the calibrated ratio, chosen on 2025 and backtested on 2026 (src/backtest_rules.py)
    if ratio < 0.75:
        return "Passer", "probabilité d'offre unique nettement inférieure à la moyenne : plus de concurrents que d'habitude sont attendus"
    if ratio < 1.0:
        return "Passer", "probabilité d'offre unique sous la moyenne : la concurrence sera habituelle"
    if ratio >= 1.5 and local and buyer_ok and rival_streak >= 2:
        return "À étudier", "un même titulaire a remporté les dernières éditions de ce marché"
    if ratio >= 1.5 and local and buyer_ok:
        if hist_single is not None:
            return "Aller", "cet acheteur reçoit souvent une seule offre, et l'entreprise exerce déjà ce métier dans ce département"
        return "Aller", "peu de concurrents attendus, sur un métier que l'entreprise exerce déjà dans ce département"
    if not local:
        return "À étudier", "peu de concurrents attendus, mais l'entreprise n'a pas encore travaillé dans ce département"
    if not buyer_ok:
        return "À étudier", "les marchés passés de cet acheteur ont souvent reçu plusieurs offres"
    return "À étudier", "probabilité proche de la moyenne ou un peu au-dessus, sans écart net"


def facts_for(row: pd.Series, profile: dict | None) -> dict:
    """Only facts a buyer could check; no model internals (they confuse the note)."""
    proba = float(row["proba"])
    avg = _avg_rate()
    f = {
        "achat": str(row.get("libelle") or row.get("description") or "")[:160],
        "type": "appel d'offres ouvert" if row.get("source") == "BOAMP" else "projet d'achat annoncé",
        "acheteur": row.get("buyer_name") if isinstance(row.get("buyer_name"), str) else None,
        "date_limite_offres": None if pd.isna(row.get("due_date")) else row["due_date"].strftime("%d/%m/%Y"),
        "probabilite_offre_unique_pct": round(100 * proba),
        "moyenne_offre_unique_pct": None if avg is None else round(100 * avg),
        "par_rapport_a_la_moyenne": None if not avg else f"{proba / avg:.1f}".replace(".", ",") + " fois",
        "contrats_similaires_gagnes_par_l_entreprise": int(row.get("n_match", row.get("n_similar", 0))),
        "dont_dans_le_meme_departement": int(row.get("n_match_dept", row.get("n_similar_dept", 0))),
        "marches_comparables_passes_par_cet_acheteur": int(row.get("hist_n", 0)),
    }
    if pd.notna(row.get("hist_single_share")):
        f["dont_marches_avec_nombre_d_offres_connu"] = int(row.get("hist_n_lab") or row.get("hist_n", 0))
        f["part_de_ces_marches_connus_avec_une_seule_offre_pct"] = round(100 * float(row["hist_single_share"]))
    elif int(row.get("hist_n", 0)) > 0:
        f["nombre_d_offres_de_ces_marches"] = "non renseigné"
    hist_single = float(row["hist_single_share"]) if pd.notna(row.get("hist_single_share")) else None
    me = str((profile or {}).get("siren") or "")[:9]
    is_incumbent = bool(me) and str(row.get("incumbent_siren") or "").replace(".0", "")[:9] == me
    rival_streak = 0 if is_incumbent else int(row.get("incumbent_streak") or 0)
    f["recommandation"], f["raison"] = recommend(proba, avg, int(f["dont_dans_le_meme_departement"]), hist_single,
                                                 is_incumbent, rival_streak)
    f["l_entreprise_est_le_titulaire_sortant"] = is_incumbent
    if rival_streak >= 2:
        f["editions_consecutives_gagnees_par_le_meme_titulaire"] = rival_streak
    return {k: v for k, v in f.items() if v is not None}


def _numbers(text: str) -> set[str]:
    return {f"{float(n.replace(',', '.')):g}" for n in re.findall(r"\d+(?:[.,]\d+)?", text)}


def numbers_ok(note: str, facts: dict) -> tuple[bool, set[str]]:
    allowed = _numbers(json.dumps(facts, ensure_ascii=False))
    bad = {n for n in _numbers(note) if n not in allowed}
    return (not bad), bad


def pairing_ok(note: str, facts: dict) -> bool:
    """Reject 'X % des N marchés' when N is all comparable contracts but X was computed on the labelled ones."""
    n_all = facts.get("marches_comparables_passes_par_cet_acheteur")
    n_lab = facts.get("dont_marches_avec_nombre_d_offres_connu")
    pct = facts.get("part_de_ces_marches_connus_avec_une_seule_offre_pct")
    if pct is None or n_all is None or n_all == n_lab:
        return True
    return not re.search(rf"{pct}\s*%\s*(?:des|de ses|sur(?: ses)?|parmi(?: ses)?)\s*{n_all}\b", note)


def client():
    from openai import OpenAI
    key = os.environ.get("FEATHERLESS_API_KEY")
    if not key:
        raise RuntimeError("Set FEATHERLESS_API_KEY in .env")
    return OpenAI(base_url="https://api.featherless.ai/v1", api_key=key)


def complete_with(provider: str, model: str, user: str, max_tokens: int | None = None) -> tuple[str, dict]:
    """One completion from a given provider and model. Returns (text, token usage)."""
    if provider == "anthropic":
        import anthropic
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("Set ANTHROPIC_API_KEY in .env")
        r = anthropic.Anthropic().messages.create(
            model=model, max_tokens=max_tokens or 4000, system=SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        usage = {"in": r.usage.input_tokens, "out": r.usage.output_tokens}
        if getattr(r, "stop_reason", None) == "max_tokens":
            return "", usage  # cut off before finishing: treated as a failure and retried
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text"), usage
    r = client().with_options(timeout=120).chat.completions.create(
        model=model, temperature=0.2, max_tokens=max_tokens or 600,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
    )
    u = getattr(r, "usage", None)
    usage = {"in": getattr(u, "prompt_tokens", None), "out": getattr(u, "completion_tokens", None)}
    return r.choices[0].message.content or "", usage


def complete(user: str) -> str:
    """One completion from the configured provider."""
    return complete_with(PROVIDER, MODEL, user)[0]


def generate(facts: dict, retries: int = 2) -> dict:
    last = None
    for _ in range(retries + 1):
        note = complete(json.dumps(facts, ensure_ascii=False)).strip()
        note = re.sub(r"<think>.*?</think>", "", note, flags=re.S).strip()  # reasoning models
        ok, bad = numbers_ok(note, facts)
        ok = ok and pairing_ok(note, facts)
        complete_note = len(note) >= 40 and note.rstrip().endswith((".", "!", "»"))
        if ok and complete_note:  # an empty or cut-off note "passes" the number check: reject it
            return {"note": note, "verified": True, "model": MODEL}
        last = {"note": note, "verified": False, "unsupported_numbers": sorted(bad), "model": MODEL}
    return last


def load_cache() -> dict:
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def save_cache(c: dict):
    CACHE.write_text(json.dumps(c, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--siren")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()

    if a.test:
        print(generate({"achat": "Maintenance des ascenseurs", "probabilite_offre_unique_pct": 64,
                        "contrats_similaires_gagnes_par_l_entreprise": 14,
                        "meme_titulaire_sur_les_dernieres_editions": 2}))
        return

    from profiles import fit_table, profile_of, relevant
    siren = a.siren or os.environ.get("DEMO_SIREN")
    awards = pd.read_parquet(CLEAN / "awards.parquet")
    from profiles import load_all_scored
    scored = load_all_scored()
    prof = profile_of(awards, siren)
    if not prof:
        raise SystemExit(f"No past wins found for SIREN {siren}")
    t = fit_table(prof, scored, awards)
    t = relevant(t).sort_values("proba", ascending=False).head(a.top)
    cache = load_cache()
    for _, row in t.iterrows():
        key = f"{siren}:{row.get('code')}"
        res = generate(facts_for(row, prof))
        cache[key] = res
        print(f"[{'ok' if res['verified'] else 'REJECTED'}] {row.get('libelle')}\n  {res['note']}\n")
        save_cache(cache)


if __name__ == "__main__":
    main()
