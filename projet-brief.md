# Offre unique: project brief for Claude Code

*Written Sat 14 Nov 2026, ~09:00 (Paris), during Hackathon Open Data. It covers two earlier claude.ai chats: the night build and the morning fixes. Owner: Jessica, a data engineer. Repo: `~/dev/offre-unique` on her MacBook Air.*

---

## 0. How to work with me (read first)

You are taking over a working project on the morning of a one-day hackathon. **The build is done. What's left is checking, a few targeted improvements, and the pitch.**

1. **Read this whole file before doing anything.** Then read the source files you will touch. Most decisions below were tested on real data. Don't undo them without telling me why.
2. **Check the state first:** `git status` (if this isn't a git repo, run `git init && git add -A && git commit -m "baseline 14 Nov morning"` before changing anything, and keep `.env` and `data/` out of git), `ls artifacts/`, and `grep -n "follows" app.py` to see whether the "Suivre" patch is applied (see §9).
3. **Before each change, say what it does, which files it touches and how long it should take.** Wait for my go on anything over 15 minutes or anything that touches the model or the data.
4. **Environment:** macOS, zsh, BSD sed (`sed -i ''`), Homebrew Python 3.14, `.venv`. Activate with `source .venv/bin/activate`. Start the app with `python -m streamlit run app.py`. The plain `streamlit` command is broken because the venv was moved.
5. **Things that cost money or credits. Ask first:**
   - Hémicycle API calls with the live key (about 794 of 1,000 credits left; 1 credit per 100-row page).
   - Regenerating LLM notes (`rm artifacts/notes.json && python src/explain.py --top 40`, about 30 Haiku calls). Always back up first: `cp artifacts/notes.json artifacts/notes_claude.json`.
6. **Never print or commit `.env`.** It holds the Hémicycle, Anthropic and (later) Featherless keys.
7. **Timeline:** decide on any extra by **11:30**, stop adding features at **16:30**, then rehearse twice with a timer. If a task risks breaking the demo, don't do it.
8. The app UI and the notes are in **French**. Talk to me in English.

---

## 1. The event

- **Hackathon Open Data**, Hémicycle × Swanbase. Saturday 14 Nov 2026, 10:00–19:00, Paris 2e. Teams form at 10:00; demos at the end of the day (about 3 minutes each).
- **Partners:** Hémicycle (French public data: API, MCP server, Atlas software, Marianne chat), Featherless (open-weight model inference).
- **Prizes:** €1,000 of Hémicycle credits, $300 of Featherless credits, access to TheNest (Swanbase).
- **Rules that matter:**
  - no targeting or profiling of private individuals;
  - no lists of entities presented as at fault (defamation risk);
  - every result shows its source and licence;
  - results state their limits.
- **History:** in the first chat, other ideas were considered (e.g. "Sillage", a page per organisation joining HATVP lobbying, DECP contracts and amendments). They were dropped for a **single-bid tender tool designed for bidding companies, not government buyers**.

## 2. The product

**Offre unique**: the upcoming French public tenders where a company would face the least competition.

- **Main user: an SME that bids on public contracts.** It enters its SIREN. Its profile (trade and départements) is inferred from the contracts it has won. It then sees matching tenders ranked by the predicted chance of **a single bid**, plus a go / no-go (Aller / À étudier / Passer) and a short note.
- For the SME, a high single-bid chance is an **opportunity** (few or no competitors), not a risk.
- **Public-interest angle:** every time an SME bids on a tender that would otherwise get one bid, competition increases.
- **Possible buyer-side extension (not built):** show public buyers which upcoming purchases risk getting too little competition, using the same scores.

## 3. Data

| Source | What | How | Size |
|---|---|---|---|
| DECP consolidated (data.gouv.fr, parquet, ~240 MB) | Past awarded contracts, incl. `offresRecues` (number of bids) | Manual download → `data/raw/decp.parquet` | 3.39M rows → 1.83M contracts; 42.3 % have a usable bid count |
| APProch via Hémicycle (`projets_achats_publics`) | Purchases planned by buyers, mostly central State, often 2027–2029 | `src/pull_hemicycle.py approch` (live key, 106 credits) | 10,569 rows; 4,110 upcoming scored |
| BOAMP open data (DILA, Opendatasoft API, free, no key) | Calls for tender **open now**, incl. local authorities | `src/pull_boamp.py` | 7,174 notices → 6,606 with a CPV code |

- Hémicycle's library also contains "Marchés publics notifiés" (the same DECP data).
- **Hémicycle API notes:** `POST /v1/jeux/interroger`, max 100 rows per page, 1 credit per page. `decalage` is capped at 10,000 (HTTP 422 *"s'arrête à 10 000 lignes"*), so the script reads ascending, then descending. Rows are under `lignes`. Test keys (`hmc_test_`) cost 0 credits but allow 100 requests/day. Hémicycle has no BOAMP dataset; BOAMP is an outside source under the same open licence.
- **Scored table columns (BOAMP/APProch, after `load_all_scored()`)** include: `code`, `libelle` (title), `buyer_siren`, `buyer_name`, `cpv_div/grp/cls`, `dept`, `departements`, `pub_date`, `due_date`, `proba`, `factors` (JSON), `hist_n`, `hist_level`, `hist_mean_offers`, `hist_single_share`, `incumbent_siren`, `incumbent_name`, `incumbent_wins`, `incumbent_streak`, `hist_editions` (JSON), `lien_vers_la_consultation`, `source`. `fit_table()` adds `n_similar*`; `relevant()` adds `n_match`, `n_match_dept`, `match_level`.

## 4. Pipeline (run order)

```bash
python src/pull_hemicycle.py approch        # APProch → data/raw/approch.parquet
python src/prepare.py                        # DECP + APProch → data/clean/{contracts,awards,approch}.parquet
python src/check_data.py                     # report → reports/data_check.md
python src/train.py                          # main model → artifacts/model.txt, encoders.pkl, metrics.json
python src/profiles.py                       # company profiles
python src/score.py                          # APProch → data/clean/scored.parquet
python src/pull_boamp.py                     # BOAMP → data/raw/boamp.parquet
python src/prepare_boamp.py                  # → data/clean/boamp.parquet
python src/train.py --variant boamp          # model without amount/duration/clauses → *_boamp files
python src/score.py --source boamp           # → data/clean/scored_boamp.parquet
python src/explain.py --top 40               # notes for DEMO_SIREN → artifacts/notes.json
python -m streamlit run app.py
```

Only the last two steps should be needed today.

**Helpers:** `find_demo.py [--idf] [--min-risk 0.35]` (companies with real opportunities + share of active companies), `check_fit.py <siren>` (do shown tenders match the trade), `test_option_a.py` (riskiest upcoming purchases, buyer-side idea), `test_option_b.py` (BOAMP field check).

**`.env`:** `HEMICYCLE_API_KEY` (live), `ANTHROPIC_API_KEY`, `FEATHERLESS_API_KEY` (empty for now), `LLM_PROVIDER=anthropic`, `ANTHROPIC_MODEL=claude-haiku-5-5`, `FEATHERLESS_MODEL`, `DEMO_SIREN=798298899`, `SPLIT_YEAR=2025`, `MIN_YEAR=2023`.

## 5. Model and results (real data)

- **Time split:** train on 2023–2024 (285,578 labelled contracts), test on 2025–2026 (320,228 contracts never seen). Single-bid rate on the test set: **20 %**.
- **Main model (LightGBM):** AUC 0.694. Among the 10 % flagged riskiest, **49.6 %** got a single bid, against buyer history alone 42.2 % (AUC 0.639) and category rate 38.0 % (AUC 0.630).
- **BOAMP variant** (no amount, duration or clauses, which BOAMP lacks): AUC 0.682, top-10 % precision 48.5 %. Still beats the baselines.
- **Coverage:** 514 of 6,683 active Île-de-France companies (**8 %**) have at least 2 matching tenders at 35 % or more (APProch alone: 0.3 %). *Computed before the `min_wins=2` filter added this morning, so it may be a bit lower now. Rerun `find_demo.py --idf` before quoting it.*

## 6. Design decisions (and why)

- **Excluded from training:** "sans publicité ni mise en concurrence" procedures (a single bid is expected by design). Upcoming purchases with that procedure are hidden too.
- **Procedure is not a feature:** empty for ~88 % of APProch rows vs ~12 % of DECP rows; it would skew every score.
- **Buyer size (`buyer_n`) removed** from the model: it made huge buyers look risky even when their own record showed competition.
- **`MIN_YEAR=2023`:** older years have junk dates, and the single-bid rate jumps from 11 % (2020) to 25 % (2024), likely a change in the source mix.
- **Target encoding** of buyer and category rates is out-of-fold, to avoid leakage.
- **Trade matching** (`relevant()` in `src/profiles.py`): 4-digit CPV classes in the company's départements, loosening level by level only if fewer than 5 tenders fit (levels in `MATCH_LEVELS`). 2-digit divisions were too broad (a roadworks firm was shown HVAC). **Since this morning:** at least 2 similar past wins (`min_wins=2`), falling back to 1 if nothing is left.
- **Duplicates** (since this morning): `dedupe_tenders()` keeps one row per buyer (`buyer_siren`, falling back to `buyer_name`) + normalised title (lowercase, no accents, a leading reference like "26.AO.VD.061 -" and the word "et" removed), keeping the highest score.
- **Go / no-go rules** in `recommend()` in `src/explain.py` (current version):
  - **Passer** if ratio = proba / average < 1.2. Worded "inférieure à la moyenne : plus de concurrents que d'habitude" below **0.75×**, "proche de la moyenne : concurrence habituelle" from 0.75× to 1.2×.
  - **Aller** if ratio ≥ 1.5 **and** a past win of this kind in the département **and** the buyer's single-bid share ≥ 30 % (or unknown). If the buyer's history is known, the reason mentions it ("cet acheteur reçoit souvent une seule offre…").
  - **À étudier** otherwise (no local win, or buyer often gets several bids, or 1.2–1.5×).
  - The rules use the unrounded ratio. Example: "SORTIES DES CONTENEURS" shows "1,5 fois" but is just under 1.5, so it's À étudier.
- **The LLM only writes the note.** Its prompt frames a single bid as an opportunity and receives checkable facts only. **Number check:** every number in a note must appear in the facts, and the note must end with a full stop. Otherwise it's rejected and the app shows a "Rédiger la note go / no-go" button. Notes are cached in `artifacts/notes.json`, keyed `"{siren}:{code}"`, with `note`, `verified`, `model`.
- **Naming companies is allowed** (legal entities, public data). Careful with sole traders, whose names are personal names.

## 7. Demo

- **Company: Moulinot Compost & Biogaz**, SIREN `798298899`, a PME (checked on annuaire-entreprises). Food-waste collection and composting, 48 public contracts won, mainly in départements 93 and 75.
- **After this morning's fixes:** **26 matching tenders. Aller 9, À étudier 3, Passer 14.** The app header shows how many are open now (BOAMP). Check it and put it in the demo line.
- **Top:** two SIREDOM tenders (Essonne waste syndicate), both 49 %, 2.5× the average, deadlines 23/11/2026 and 04/12/2026. SIREDOM got a single bid on 54 % of its 54 comparable contracts (yes, 54 and 54 %; it's real).
- **Counter-example:** Espaces TP (`753310598`, PME, Paris roadworks): top score only 12 %, because Paris roadworks are competitive. The tool doesn't flatter.
- **Rejected candidates:** Yvelines Restauration (large company); AXA, MMA (top of `find_demo`, not SMEs).
- **Demo line:** *"Moulinot has [N] open tenders matching its trade. The top one is SIREDOM, closing on 23 November: a 49 % chance of a single bid, 2.5× the average, and this buyer got one bid on more than half of its comparable contracts. Of 26 tenders, the tool says go for 9, look closer at 3 and skip 14."*
- **On stage:**
  1. Open the SIREDOM tender that closes on 23/11 (Aller). Read the note.
  2. Click **Suivre cet appel d'offres**; it appears in the sidebar with "J-9".
  3. Click **Grand Cubzaguais** (Passer, 12 %, 6 comparable contracts, none single-bid).
  4. Show the **Preuves** tab.
  - **Don't open "Détail des marchés passés".** Its "historique de l'acheteur (21 %)" factor is the model's fallback average, not real history.
  - Before the demo: `rm -f artifacts/follows.json` so the follow list starts empty.

## 8. What changed this morning (14 Nov, 07:40–08:50)

Backups: `src/explain.py.bak`, `src/profiles.py.bak`, `app.py.bak`, `artifacts/notes_before_fix.json`.

1. Passer wording split at 0.75× (was "proche de la moyenne" even at 9 %).
2. Aller reason mentions the buyer when known, so 9 notes don't end identically.
3. `relevant(min_wins=2)` removed off-trade tenders for Moulinot (graffiti products, machine-tool maintenance, fire-safety maintenance).
4. `dedupe_tenders()` removed duplicate notices (EPT Grand-Orly; PEECS Anatole, whose two notices had buyer names "EPT Est Ensemble" vs "EST ENSEMBLE DAAJCP" but the same SIREN 200057875).
5. Notes regenerated with Claude Haiku. Output checked by hand: all numbers match the facts.
6. **"Suivre cet appel d'offres" made functional** (see §9).

## 9. "Suivre" feature (patch sent at 08:50; verify it's applied)

- Before: the button only showed a toast.
- Patch: `load_follows()`, `save_follows()`, `days_left()`, `reco_of()`, `render_follows()` added after `load_notes()` in `app.py`. The button saves `{title, buyer, due, when, risk, reco, url, source, followed_at}` to `artifacts/follows.json` under key `"{siren}:{code}"`, then calls `st.rerun()`. A followed tender shows a disabled "✓ Suivi" button. The sidebar lists the company's followed tenders sorted by deadline, with "J-n", score, recommendation, "Voir l'avis" link and a "Retirer" button. At the end of the file: `if siren and prof: render_follows(prof["siren"])`.
- The sidebar says reminders and change alerts are the **next step**. Don't claim they work.
- **Verify:** `python -m py_compile app.py`, then in the app follow SIREDOM, reload the page, remove it.

## 10. Hémicycle context and pitch material

- Hémicycle collects Assemblée, Sénat, Légifrance, JO, HATVP and press nightly, links texts, amendments, votes and elected officials, and sells **Atlas** (public-affairs software: veille, alerts by email/Telegram, vote prediction, deliverables; from €720 HT/month), an **API** (prepaid credits) and an **MCP server**. Main users: public-affairs teams. Their models: **Orcet** predicts each deputy's vote (84 % vs 56.8 % for the usual group position) and **Marianne** answers questions with sources.
- **Marianne test (this morning):** asked what share of waste contracts get a single bid, it answered ~**23.5 %** (2,613 of 11,117 rows mentioning "déchet", "Marchés publics notifiés", since 2023), with a caveat that it counted rows, not deduplicated contracts. That's consistent with our 20 % baseline.
- **Pitch lines:**
  - *"Marianne tells you 1 waste contract in 4 got a single bid. We tell an SME which open ones will."*
  - Show Preuves like Hémicycle shows Orcet: **49.6 % vs 42.2 % (buyer history) vs 20 % (average)**.
  - Their "Que peut-on construire ?" page suggests "Un agent de veille sur la commande publique" (Projets d'achats publics + Marchés publics notifiés). We go further: prediction, matched to one company, with a go / no-go.
  - An SME tool brings a new kind of user to their data.
  - EU context: the European Commission's Single Market Scoreboard tracks the share of contracts with a single bidder as one of its main procurement indicators. France was at 22 % in 2024 vs an EU average of 28 % (TED contracts, a different scope from DECP). Above 20 % is rated red. Source: https://single-market-scoreboard.ec.europa.eu/node/276_de and https://single-market-scoreboard.ec.europa.eu/node/264_et

## 11. Limits to state

- Only 42 % of contracts report the number of bids, and the model learns from those.
- APProch is mostly central State. BOAMP has no amount, hence the variant model.
- The score describes past patterns, not causes. Repeat wins by the same company indicate nothing wrong in themselves.
- AUC 0.69 is a moderate ranking. Present the score as useful, not precise.

## 12. Open tasks, in priority order

Time-box each one. Stop at 16:30 whatever happens.

### A. Verify the app (10 min, do first)
Header shows 26 tenders and N open. The SIREDOM note shows. "Voir l'avis BOAMP" opens the notice. "Suivre" works (§9). Then `cp artifacts/notes.json artifacts/notes_claude.json`.

### B. Incumbent check (15–30 min). This is the biggest gap in the model's story.
The score predicts **how many bids a tender will get from the usual bidders**, not **whether this SME would win**. A single bid often means an **installed incumbent** (or tailored specs), which is exactly where a newcomer is least likely to win. The data already has `incumbent_siren`, `incumbent_name` and `incumbent_streak`, and `fact_sentences()` displays "Le même titulaire a gagné les N dernières fois". But `recommend()` ignores it.
1. **First, check:** for Moulinot's 26 tenders, how many have `incumbent_siren == "798298899"` (Moulinot is the outgoing holder) and how many have another company with `incumbent_streak >= 2`. Report before changing anything.
2. **If Moulinot is the incumbent somewhere:** show "Vous êtes le titulaire sortant" in the app and pass it to the note facts. That's a renewal to defend, and a strong demo moment.
3. **Proposed rule change (ask me first):** another company with `incumbent_streak >= 2` turns Aller into À étudier, with the reason "un même titulaire a remporté les dernières éditions". Update the note facts and the number check if new numbers appear. Regenerate only the affected notes.

### C. Backtest the go / no-go rules (30–45 min). This is the biggest gap in the use case's evidence.
The Preuves tab validates the **score**, but the product's output is the **go / no-go**, and it isn't validated. On the 2025–26 test set:
- apply the rules that don't need a company: ratio thresholds (1.2 / 1.5) plus the buyer's single-bid share from the **train period only** (≥ 30 % or unknown);
- report, for Aller / À étudier / Passer, the number of contracts and the share that actually got a single bid. Expected shape: Aller far above 20 %, Passer below.
- Add one line to the Preuves tab, e.g. *"Sur les marchés 2025–26, ceux que les règles auraient classés « Aller » ont reçu une seule offre dans X % des cas, contre Y % pour « Passer »."*
- Watch for leakage: buyer history must come from before the test period.

### D. Wording against misreading (5 min)
In the EU, single bidding is a standard **warning sign** of weak competition. A judge could read "cet acheteur a eu une seule offre dans 54 % des cas" as an accusation of the buyer. Add to the Limites list in `app.py`: *"Une offre unique ne signale pas en soi une irrégularité de l'acheteur : elle peut venir d'un marché étroit ou très spécialisé."* Keep the framing in the pitch on opportunity and competition, never on buyers at fault.

### E. Slides and backup video (outside the code)
2–3 slides: the hook ("1 public contract in 5 gets a single bid"; EU red line at 20 %), Preuves (50 / 42 / 20, plus the backtest line if C is done), coverage (6,606 open + 4,110 planned). Record a 60-second backup video of the demo.

### F. Featherless (only if the key arrives)
1. Pick a non-reasoning, French-capable instruct model.
2. Set `LLM_PROVIDER=featherless`, `FEATHERLESS_API_KEY`, `FEATHERLESS_MODEL` in `.env`.
3. `python src/explain.py --test`.
4. Back up: `cp artifacts/notes.json artifacts/notes_claude.json`.
5. Regenerate: `rm artifacts/notes.json && python src/explain.py --top 40`.
6. Compare quality, keep the better set, restart the app.
7. Only say "Featherless" in the pitch if the demo notes come from it (`notes.json` records the model per note).

### G. Optional: buyer-side tab (1–1.5 h; only if A–D are done by 11:30)
85 upcoming purchases are at 50 % or more, 52 of them from the armed forces (catering and food supply). Frame it as "where buyers should expect too little competition", never as a ranking of buyers.

## 13. Pitch (about 3 min)

- Problem (20 s): 1 public contract in 5 gets a single bid; less competition means worse value for public money and fewer contracts for SMEs.
- Who it's for (15 s): an SME that bids.
- Live demo (90 s): Moulinot → SIREDOM (Aller) → Suivre → Grand Cubzaguais (Passer) → note.
- Proof (30 s): Preuves tab.
- Close (15 s): *"Each SME that bids turns a single-bid tender into a competitive one."* Buyer side and alerts as next steps.

**Lines for questions**
- *"The go / no-go is three explicit rules. The LLM only writes them up, and any number it writes is checked against the data."*
- *"We trained on 2023–24 and tested on 320,000 contracts from 2025–26 the model never saw."*
- *"If every SME used it, the scores would drop. That's the point: more bids on those tenders."*
- *"It predicts how many bids a tender gets, not whether you win. That's why the note also shows the buyer's history and the outgoing holder."* (true once task B is done)

## 14. Files

```
app.py                  Streamlit app: "Appels d'offres" and "Preuves" tabs; follows sidebar
src/common.py           paths (ART, CLEAN), column aliases, aligned features, CPV labels
src/pull_hemicycle.py   Hémicycle pull (offset cap, partial save)
src/test_api.py         4-request API check (free with a test key)
src/prepare.py          DECP + APProch cleaning and features
src/check_data.py       data report and verdict
src/train.py            time split, baselines, LightGBM; --variant boamp
src/profiles.py         profiles, fit_table, relevant(min_wins), dedupe_tenders, load_all_scored
src/score.py            scoring + buyer history; --source boamp
src/pull_boamp.py       BOAMP pull, CPV/SIRET extraction from 'donnees'
src/prepare_boamp.py    BOAMP → APProch-like columns
src/explain.py          recommend() rules + facts_for + LLM note (Claude or Featherless) + number check
find_demo.py, check_fit.py, test_option_a.py, test_option_b.py
tests/make_fake_data.py, tests/fake_boamp_pull.py   offline test data
artifacts/              model, metrics(.json), notes.json, follows.json
.streamlit/config.toml  hides the developer menu
```

## 15. Your first reply

Read this file and run the checks in §0.2. Then reply with:
1. the state you found (git, whether the follow patch is applied, which artifacts exist);
2. what you'll do for task A;
3. confirmation that you'll run §16 in order, starting with D and B1.

Don't change any code until I say go.

---

## 16. Implementation of tasks B, C and D

Order: **D (2 min) → B1 check (5 min) → B2 (20 min, only if B1 finds something) → C (45 min, only if before 11:30)**. Commit to git after each step. Run `python -m py_compile` on every edited file, then open the app and check SIREDOM still shows.

The patches below match `app.py` and `recommend()` as they were at 09:15. If an `assert` fails, read the current file and adapt; don't force it.

### D + the "titulaire sortant" sentence (app.py, exact patch)

```bash
python - <<'EOF'
import pathlib
p = pathlib.Path("app.py"); s = p.read_text()
pairs = [
 ('''            "- Un titulaire qui gagne plusieurs fois n'indique en soi aucune irrégularité."
        )''',
  '''            "- Un titulaire qui gagne plusieurs fois n'indique en soi aucune irrégularité.\\n"
            "- Une offre unique ne signale pas en soi une irrégularité de l'acheteur : elle peut venir d'un marché étroit ou très spécialisé."
        )'''),
 ('def fact_sentences(r: pd.Series) -> list[str]:',
  'def fact_sentences(r: pd.Series, siren: str = "") -> list[str]:'),
 ('''    streak = int(r.get("incumbent_streak", 0))
    if streak >= 2:''',
  '''    streak = int(r.get("incumbent_streak", 0))
    inc = str(r.get("incumbent_siren") or "").replace(".0", "")[:9]
    if siren and inc == str(siren)[:9]:
        out.append("Vous êtes le titulaire sortant : ce marché est un renouvellement à défendre.")
    elif streak >= 2:'''),
 ('        for s in fact_sentences(r):',
  '        for s in fact_sentences(r, prof["siren"]):'),
]
for old, new in pairs:
    assert s.count(old) == 1, f"not found:\n{old[:80]}"
    s = s.replace(old, new)
p.write_text(s); print("patched app.py")
EOF
```

### B1: incumbent check for Moulinot (read-only)

```bash
cd src && python - <<'EOF'
import pandas as pd
from common import CLEAN
from profiles import profile_of, fit_table, relevant, load_all_scored
siren = "798298899"
scored = load_all_scored(); awards = pd.read_parquet(CLEAN / "awards.parquet")
prof = profile_of(awards, siren)
t = relevant(fit_table(prof, scored, awards)).sort_values("proba", ascending=False)
t["inc"] = t["incumbent_siren"].astype(str).str.replace(r"\.0$", "", regex=True).str[:9]
t["moulinot_holds_it"] = t["inc"] == siren
cols = ["libelle", "buyer_name", "proba", "incumbent_name", "incumbent_streak", "incumbent_wins", "moulinot_holds_it"]
pd.set_option("display.width", 250, "display.max_colwidth", 45)
print(t[cols].to_string(index=False))
print("\nMoulinot holds:", int(t["moulinot_holds_it"].sum()),
      "| another holder with streak >= 2:", int(((~t["moulinot_holds_it"]) & (t["incumbent_streak"].fillna(0) >= 2)).sum()))
EOF
cd ..
```

Report the result to me before B2. If both counts are 0, skip B2: the demo doesn't change, and the "titulaire sortant" sentence from D is enough.

### B2: incumbent in the go / no-go rules (src/explain.py)

1. Patch `recommend()` (exact):

```bash
python - <<'EOF'
import pathlib
p = pathlib.Path("src/explain.py"); s = p.read_text()
pairs = [
 ("def recommend(proba: float, avg: float | None, n_dept: int, hist_single: float | None) -> tuple[str, str]:",
  "def recommend(proba: float, avg: float | None, n_dept: int, hist_single: float | None,\n"
  "              is_incumbent: bool = False, rival_streak: int = 0) -> tuple[str, str]:"),
 ("    buyer_ok = hist_single is None or hist_single >= 0.30\n",
  "    buyer_ok = hist_single is None or hist_single >= 0.30\n"
  "    if is_incumbent:\n"
  "        return \"Aller\", \"l'entreprise est le titulaire sortant : un renouvellement à défendre\"\n"),
 ("    if ratio >= 1.5 and local and buyer_ok:\n",
  "    if ratio >= 1.5 and local and buyer_ok and rival_streak >= 2:\n"
  "        return \"À étudier\", \"un même titulaire a remporté les dernières éditions de ce marché\"\n"
  "    if ratio >= 1.5 and local and buyer_ok:\n"),
]
for old, new in pairs:
    assert s.count(old) == 1, f"not found:\n{old[:80]}"
    s = s.replace(old, new)
p.write_text(s); print("patched recommend()")
EOF
```

2. **Find the call to `recommend(` in `facts_for()`** and pass the two new arguments, computed from the row and the profile:
   - `is_incumbent = str(row.get("incumbent_siren") or "").replace(".0", "")[:9] == str(prof["siren"])[:9]`
   - `rival_streak = 0 if is_incumbent else int(row.get("incumbent_streak") or 0)`
3. **Add both to the facts dict** sent to the LLM, so the note can mention them and the number check accepts the streak: `"l_entreprise_est_le_titulaire_sortant": is_incumbent` and, only when `rival_streak >= 2`, `"editions_consecutives_gagnees_par_le_meme_titulaire": rival_streak`. Don't pass the incumbent's name.
4. Check the LLM prompt still makes sense with these facts. Run `python src/explain.py --test` if it exists.
5. Back up and regenerate: `cp artifacts/notes.json artifacts/notes_claude.json && rm artifacts/notes.json && python src/explain.py --top 40`. Show me the new Aller / À étudier / Passer counts, and update the demo line in §7 if they changed.

### C: backtest of the rules (new script `src/backtest_rules.py`)

Goal: show that tenders the rules mark Aller really got a single bid more often. Read `src/train.py` first and reuse its test split and feature building. Don't duplicate logic, and don't retrain.

- **Data:** the 2025–26 labelled test contracts (the same 320,228 as in `metrics.json`) and predictions from the saved model (`artifacts/model.txt` + `encoders.pkl`). Check that the AUC you get matches `metrics.json` (0.694) before going on. If it doesn't, stop and tell me.
- **Average:** `test_single_bid_rate` from `metrics.json`. Ratio = prediction / average.
- **Buyer history, train period only (2023–24),** to avoid leakage: the raw single-bid share per buyer × `cpv_grp` if it has ≥ 3 labelled contracts, otherwise per buyer if ≥ 3, otherwise unknown. This mirrors `hist_single_share` in the app.
- **Rules:** the same as `recommend()` minus the département condition, which needs a company. Aller = ratio ≥ 1.5 and (buyer share ≥ 0.30 or unknown). À étudier = ratio ≥ 1.2 otherwise. Passer = ratio < 1.2.
- **Output** `artifacts/rules_backtest.json`:
  `{"years": "2025–2026", "note": "sans la condition de département", "groups": {"Aller": {"n": ..., "single_rate": ...}, "À étudier": {...}, "Passer": {...}}}`
  Also print it.
- **Sanity check:** Aller's single-bid rate should be well above 20 % and Passer's below. If Aller isn't clearly above À étudier, report it. Don't show it in the app; that's a finding, not a slide.

Then add one line to the Preuves tab (exact patch, after the three metrics):

```bash
python - <<'EOF'
import pathlib
p = pathlib.Path("app.py"); s = p.read_text()
old = '''        c3.metric("Moyenne, sans score", f"{round(100 * avg)} %")\n'''
new = old + '''        bt_p = ART / "rules_backtest.json"
        if bt_p.exists():
            bt = json.loads(bt_p.read_text())
            g = bt["groups"]
            st.write(f"Les règles go / no-go, appliquées aux marchés {bt['years']} ({bt['note']}) : "
                     + " · ".join(f"« {k} » {round(100 * g[k]['single_rate'])} % d'offres uniques ({fr_int(g[k]['n'])} marchés)"
                                  for k in ("Aller", "À étudier", "Passer") if k in g) + ".")
'''
assert s.count(old) == 1, "anchor not found"
p.write_text(s.replace(old, new)); print("patched Preuves tab")
EOF
```

Finally, add the result to the pitch's proof slide and to the Q&A lines in §13.
