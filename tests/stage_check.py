"""Stage check: runs the live demo path and the hands-on edge cases headless. Must print 34/34 PASS.

    python tests/stage_check.py

Run it after ANY change to app.py (UI included). It uses Streamlit's AppTest (no browser, no server).
Side effects: none on shared files (follows are per session). It reads artifacts/ and data/; the
sole-trader check calls the public company register (recherche-entreprises.api.gouv.fr).
"""
import time, json
from pathlib import Path
from streamlit.testing.v1 import AppTest
ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")
RESULTS = {"pass": 0, "fail": 0}


def ok(c, msg):
    RESULTS["pass" if c else "fail"] += 1
    print(("PASS " if c else "FAIL ") + msg)
t0 = time.time(); at = AppTest.from_file(APP, default_timeout=300)
at.session_state["entered"] = True  # skip the welcome page (tested separately in tests/welcome_check.py)
at.run(); cold = time.time() - t0
ok(not at.exception, f"cold start {cold:.1f}s, no exception")
ok(at.subheader[0].value == "Point Contrôles", "demo company loads by default")
cap = [c.value for c in at.caption if "appels d'offres dans" in c.value]
ok(cap and "62 appels" in cap[0] and "39 ouverts" in cap[0], f"list header: {cap[0] if cap else None}")
md = [m.value for m in at.markdown]
ok(any("Mission de coordination" in m for m in md), "SENEO selected (top row)")
ok(any("**53 %**" in m and "2,7" in m for m in md), "53 % · 2,7 × la moyenne")
note = [m for m in md if m.startswith("La probabilité") and "Aller, car" in m]
ok(bool(note), f"SENEO note shown: {note[0][:90] if note else None}")
ok(any("En direct d'Hémicycle" in c.value for c in at.caption), "Hémicycle panel (cached)")
ok(any(e.label.startswith("Vos contrats similaires (8)") for e in at.expander), "Vos contrats similaires (8)")
ok("J-16" in at.dataframe[0].value["Échéance"].iloc[0], f"countdown: {at.dataframe[0].value['Échéance'].iloc[0]}")
# Suivre -> sidebar J-16 -> Retirer
b = [x for x in at.button if x.label == "Suivre cet appel d'offres"]
ok(bool(b), "Suivre button present (follow list empty)")
if b:
    b[0].click().run()
    side = [c.value for c in at.sidebar.caption]
    ok(any("J-16" in c for c in side), f"sidebar after Suivre: {[c for c in side if 'J-' in c][:1]}")
    r = [x for x in at.sidebar.button if x.label == "Retirer"]
    if r: r[0].click().run()
    f = ROOT / "artifacts" / "follows.json"
    ok(not f.exists() or not json.loads(f.read_text()), "follow list empty again after Retirer")
# Val-de-Marne (Passer)
# Preuves
metrics = {m.label: m.value for m in at.metric}
ok(metrics.get("Notre score") == "50 %" and metrics.get("Historique de l'acheteur seul") == "42 %", "Preuves 50 / 42 / 20")
ok(metrics.get("« Aller »") == "41 %" and metrics.get("« Passer »") == "12 %", "backtest 41 / 23 / 12")
ok(any("Pour qui" in m for m in md), "coverage line")
ok(len(at.dataframe[-1].value) == 8, "benchmark table: 8 models")
# backup + edge cases
cases = [("481447951", "Bati Recyclage", None), ("883266645", None, "entrepreneur individuel"),
         ("123456789", None, "fictif"), ("abc", "Abcd", None), ("12", None, "9 chiffres"), ("632041071", None, "pas un SIREN valide"),
         ("83470924800012", "Point Contrôles", None), (" 834 709 248 ", "Point Contrôles", None),
         ("329338883", "Colas France", None), ("356000000", None, None)]
for s, head, msg in cases:
    at.text_input[0].set_value(s).run()
    h = at.subheader[0].value if at.subheader else None
    txt = " ".join(m.value for m in at.markdown)
    good = not at.exception and (head is None or h == head) and (msg is None or msg in txt)
    ok(good, f"SIREN {s!r}: header={h} | {'expected message found' if msg and msg in txt else (txt[:70] if not head else '')}")
at.text_input[0].set_value("481447951").run()
ok(any("titulaire sortant" in m.value for m in at.markdown), "backup: 'Vous êtes le titulaire sortant' on Trivalis")
# --- hands-on additions (public link)
at.text_input[0].set_value("colas").run()
ok(at.subheader and at.subheader[0].value == "Colas France" and at.selectbox, "name search 'colas' -> Colas France (with list)")
at.text_input[0].set_value("lecouteux").run()
ok(not at.selectbox and not at.subheader, "sole trader not listed in name search")
at.text_input[0].set_value("donnees personnelles").run()
ok(not at.selectbox, "non-diffusible entities not listed in name search")
at.text_input[0].set_value("848531554").run()
ok(not at.subheader and any("non diffusible" in m.value for m in at.markdown), "non-diffusible SIREN refused")
exb = [b for b in at.button if str(b.key).startswith("ex_")]
ok(len(exb) == 3, f"example buttons: {[b.label for b in exb]}")
[b for b in at.button if str(b.key) == "ex_480980358"][0].click().run()
ok(at.subheader and at.subheader[0].value == "Adimeo", "example button -> Adimeo")
import sys; sys.path.insert(0, str(ROOT))
src = open(APP, encoding="utf-8").read()
ns = {"re": __import__("re")}; exec(src[src.index("COMPANY_WORDS = "):src.index("# Followed tenders")], ns)
lp = ns["looks_like_person"]
ok(lp("Claire Lecouteux", 1) and not lp("Point Contrôles", 101) and not lp("Bati Recyclage", 57) and not lp("SAS Morisset", 3),
   "offline rule: person-like names refused, companies kept")

print(f"\n{RESULTS['pass']} PASS / {RESULTS['fail']} FAIL")
sys.exit(1 if RESULTS["fail"] else 0)
