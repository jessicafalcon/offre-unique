# webdesign/: redesigned Offre unique pages

A **separate** Streamlit app with a new visual design, inspired by echarts.streamlit.app, and two new pages: a company portrait and the pipeline.

- **It changes nothing in the existing project.** `app.py`, `src/`, `artifacts/`, `data/` and `requirements.txt` are untouched. The folder only *reads* them: it imports `src/` and reads the artifacts and parquet files.
- You can keep iterating on the main app as before. These pages pick up your changes to `src/` automatically (see "How it plugs into src/").
- It was built from the plan in [PLAN.md](PLAN.md).

## Run

```bash
pip install -r webdesign/requirements.txt          # your requirements + streamlit-echarts==0.7.0
cd webdesign
../.venv/bin/python -m streamlit run app.py         # macOS
../.venv/Scripts/python -m streamlit run app.py     # Windows
```

- **Start it from `webdesign/`.** Streamlit reads the theme from `webdesign/.streamlit/config.toml` in the current folder. The main app keeps its own `.streamlit/config.toml`.
- **Both apps can run side by side.** The main app uses port 8501. Streamlit picks the next free port for this one, or you can pass `--server.port 8502`.
- **It needs the same local data as the main app.** That is the files in `data/clean/`, including `awards.parquet`, which is not in git.
- **Restart after editing `lib/`.** Streamlit re-runs `views/` on reload, but not always the `lib/` modules.

## The four pages (`views/`)

| Page | Files | What it shows |
|---|---|---|
| **Votre entreprise** (default) | `views/entreprise.py`, `lib/entreprise_widgets.py` | <ul><li>Header: name, NAF activity, head office, creation year, labels</li><li>Size picto (🌱 🌿 🌳 🏢 🏙️ plus 1–5 people icons), sector, revenue (only when > 0; net result never shown)</li><li>KPIs: contracts, median amount, clients, départements, share won as sole bidder, last win</li><li>Charts by client type, top clients, amount band, kind of service, year, département</li><li>Grid of the 11 buyer kinds</li><li>Under 5 wins: a "profil en construction" card and a plain list instead of near-empty charts</li></ul> |
| **Appels d'offres** | `views/appels.py`, `lib/appels_widgets.py` | <ul><li>KPIs and the Aller / À étudier / Passer bar</li><li>"Qui achète ?" donut, kinds of contract, chance-vs-deadline scatter (next 90 days)</li><li>Sort and filters (recommendation, buyer kind, open/project, sector, text search)</li><li>Cards or table</li><li>Detail panel: gauge, facts, cached verified note, buyer's past comparable contracts, "Voir l'avis", "Suivre"</li></ul> |
| **Preuves** | `views/preuves.py`, `lib/proof_widgets.py` | Same content as the main Preuves tab (metrics, rules backtest, calibration, LLM benchmark, sources, every limit sentence word for word), redesigned. Every number is read from `artifacts/*.json` |
| **Comment ça marche** | `views/pipeline.py`, `lib/proof_widgets.py` | 7-step diagram, data funnel (3.39 M DECP rows to the 2026 test), feature importances, time split, the three rules and their 2026 results |

The sidebar holds the SIREN field, the followed tenders on every page, and the sources.

## Shared building blocks (`lib/`)

| File | Role |
|---|---|
| `taxonomy.py` | Pictos, labels and colours (pure functions, no I/O). See the list below. |
| `data.py` | Data access on top of `src/`, kept light on RAM. See below. |
| `charts.py` | ECharts helpers with the shared style: `render`, `donut`, `hbar`, `gauge`. |
| `ui.py` | CSS, KPI cards, chips, badges, source lines. |
| `fmt.py` | French numbers (`fr_int`, `fr_pct`, `fr_eur`) and `plural`. |
| `naf.py` | NAF rév. 2 code to French label. |

`taxonomy.py` covers:
- company size, from the INSEE headcount band;
- 16 sectors, from the CPV division or the NAF code;
- 11 buyer kinds, from the INSEE nature juridique with the buyer's name as fallback;
- amount bands;
- the chance of a single bid;
- Aller / À étudier / Passer.

`data.py` details:
- `tenders(siren)` calls your `profile_of`, `fit_table`, `relevant` and `recommend` unchanged, then adds display tags: `reco`, `reason`, `sector`, `buyer_kind`, `amount_rank`, `days_left`, `kind`.
- It never loads the full awards file: it reads it row group by row group, which peaks at about 0.4 GB.
- Every JSON file is read as UTF-8. On Windows, a plain `read_text()` breaks the "À étudier" key.
- Placeholder SIRENs such as `999999999` are rejected.

## Extra data (`data/`, `scripts/`)

All of it is public open data under Licence Ouverte 2.0.

| File | Content | How to rebuild |
|---|---|---|
| `data/buyers.parquet` | 2,701 buyer SIRENs with their INSEE nature juridique, commune and département: every buyer of a scored tender, plus the past buyers of Point Contrôles and Moulinot. | `python webdesign/scripts/enrich_buyers.py`. Free API Recherche d'entreprises, ≤ 6 requests/s, resumable through `data/buyers_cache.jsonl`. |
| `data/companies/<siren>.json` | Company cards: size, NAF, creation date, head office, revenue, labels. | `python webdesign/scripts/enrich_companies.py <siren> ...`. The page also fetches and caches a card live the first time a SIREN is entered. |
| `data/naf.json` | NAF labels (1,707 codes). | Derived from INSEE via github.com/SocialGouv/codes-naf. |
| `data/hemicycle_sirene_834709248.json` | Point Contrôles in Hémicycle's `sirene_etablissements` dataset. | `python webdesign/scripts/hemicycle_sirene.py` (**1 credit**). |

**Your `artifacts/buyers.json` overlaps with `data/buyers.parquet`** (commit 83279da, SIRENE via recherche-entreprises, so the same source). They were built in parallel:
- Yours adds the location and the multi-site flag.
- This one adds the nature juridique, which drives the 11 buyer kinds.

With it, only 5 % of scored tenders still have a buyer classed as "autre", against 30 % from names alone. If you'd rather keep one file, `data.buyer_kind_key()` is the only function to repoint.

## How it plugs into `src/` (what can break, and what can't)

Imports from `src/`:
- `common`: `ART`, `CLEAN`, `TODAY`, `cpv_label`
- `profiles`: `profile_of`, `fit_table`, `relevant`, `load_all_scored`
- `explain`: `recommend`

Artifacts it reads: `metrics.json`, `metrics_boamp.json`, `rules_backtest.json`, `llm_benchmark.json`, `notes.json`, `hemicycle_history.json`.

What follows from that:
- If you change the scores, the rules or the notes, the pages show the new values. Nothing is hard-coded.
- If you rename one of these functions or artifact keys, update `lib/data.py` and `lib/proof_widgets.py`.
- The new columns from your `load_all_scored()` don't clash with the tags added here: `taille`, `nature_achat`, `procedure_note` and `buyer_type` are yours; `reco`, `sector`, `buyer_kind` and `kind` are these pages'.
- The pages make **no LLM calls and no Hémicycle calls**. They show the cached notes and the cached buyer history.
- **"Suivre" lives in the session only.** It does not write `artifacts/follows.json`.

## Reusing pieces in the main app

To bring one element into `app.py` without switching apps, copy `lib/` (plus `streamlit-echarts` if you need charts), then:

| Element | Code |
|---|---|
| Go / no-go badge | `ui.reco_badge_html(reco)` |
| Chips | `ui.chip_html(tx.sector_of(cpv_div))` |
| Buyer kind | `tx.buyer_kind_of(cat_juridique, name)` |
| Gauge | `charts.gauge(...)` |
| Preuves charts | the functions in `proof_widgets.py` |

The whole folder can also be merged as it is, because the pages already use `st.navigation`.

## Tested (14 Nov 2026, against `origin/main` at 83a24b2)

A headless Edge browser (Playwright) ran the full user journey:

1. Enter the SIREN.
2. Open Votre entreprise.
3. Follow the link to Appels d'offres.
4. Pick a tender.
5. Click Suivre.
6. Open Preuves.
7. Open Comment ça marche.

SIRENs tested:
- Point Contrôles 834709248: 62 tenders, 39 open, Aller 3 / À étudier 4 / Passer 55, SENEO first at 53 %
- Bati Recyclage 481447951: 2 / 3 / 2, Trivalis first
- MAS Entreprise 423618628 (building works, Marseille)
- Moulinot 798298899
- Idverde 339609661 (1,223 tenders)
- SARL Andreatta 301224028 (1 win)
- placeholder 999999999 (refused)

Results:
- 0 Streamlit exceptions and 0 JavaScript errors.
- Followed tenders stay in the sidebar across pages.
- Every chart was checked on screenshots.

Known leftovers:
- Chart tooltips use a decimal point (it needs a JS formatter).
- The ♻️ emoji doesn't render inside ECharts canvas labels.
- First load of a very large company (Idverde) takes a few seconds.
