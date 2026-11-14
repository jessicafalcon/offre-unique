"""Synthetic DECP + APProch files with the real column names, to test the pipeline end to end.

    python tests/make_fake_data.py      -> data/raw/decp.parquet, data/raw/approch.parquet
Do NOT run this once you have real data: it overwrites data/raw/.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from common import RAW  # noqa: E402

rng = np.random.default_rng(42)
N, NB, NC = 60_000, 800, 3_000
buyers = [f"{rng.integers(100000000, 999999999)}{rng.integers(10000, 99999)}" for _ in range(NB)]
buyer_bias = rng.normal(0, 1, NB)
companies = [f"{rng.integers(100000000, 999999999)}00012" for _ in range(NC)]
cpvs = ["45000000", "50700000", "33100000", "72000000", "79000000", "30190000", "90900000", "71000000", "09100000", "15800000"]
cpv_bias = dict(zip(cpvs, rng.normal(0, 0.8, len(cpvs))))
procs = ["Appel d'offres ouvert", "Procédure adaptée", "Procédure avec négociation",
         "Marché passé sans publicité ni mise en concurrence préalable", "Appel d'offres restreint"]
proc_bias = dict(zip(procs, [0.0, 0.3, 0.5, 3.0, -0.2]))
depts = ["75", "92", "93", "94", "77", "69", "13", "33", "59", "2A"]

b = rng.integers(0, NB, N)
cpv = rng.choice(cpvs, N)
proc = rng.choice(procs, N, p=[0.3, 0.45, 0.1, 0.1, 0.05])
montant = np.exp(rng.normal(11.5, 1.5, N)).round(2)
duree = rng.choice([6, 12, 24, 36, 48, 60], N)
dept = rng.choice(depts, N)
logit = -1.4 + buyer_bias[b] + np.array([cpv_bias[c] for c in cpv]) + np.array([proc_bias[p] for p in proc]) \
        + 0.15 * (duree / 12) - 0.2 * (np.log(montant) - 11.5)
p1 = 1 / (1 + np.exp(-logit))
offres = np.where(rng.random(N) < p1, 1, rng.integers(2, 9, N))
offres = np.where(rng.random(N) < 0.08, 0, offres)  # missing-ish values
dates = pd.to_datetime("2022-01-01") + pd.to_timedelta(rng.integers(0, 365 * 4 + 300, N), unit="D")
# companies specialise: company index tied to cpv + dept
comp_idx = (np.array([cpvs.index(c) for c in cpv]) * 300 + np.array([depts.index(d) for d in dept]) * 30
            + rng.integers(0, 30, N)) % NC

decp = pd.DataFrame({
    "uid": [f"{buyers[i]}{k}" for k, i in enumerate(b)],
    "id": [f"2024-{k:06d}" for k in range(N)],
    "acheteur_id": [buyers[i] for i in b],
    "acheteur_nom": [f"Acheteur {i}" for i in b],
    "objet": [f"Marché {c[:2]} n°{k}" for k, c in enumerate(cpv)],
    "codeCPV": cpv,
    "procedure": proc,
    "nature": "Marché",
    "montant": montant,
    "dureeMois": duree,
    "dateNotification": dates.strftime("%Y-%m-%d"),
    "offresRecues": offres,
    "lieuExecution_code": [f"{d}{rng.integers(100, 999)}" if d != "2A" else "20000" for d in dept],
    "lieuExecution_typeCode": "Code postal",
    "titulaire_id": [companies[i] for i in comp_idx],
    "titulaire_denominationSociale": [f"Société {i}" for i in comp_idx],
    "considerationsSociales": rng.choice(["Pas de considération sociale", "Clause sociale"], N),
    "considerationsEnvironnementales": rng.choice(["Pas de considération environnementale", "Critère environnemental"], N),
    "modification_id": 0,
})
decp.to_parquet(RAW / "decp.parquet", index=False)

M = 1_500
ab = rng.integers(0, NB, M)
a_cpv = rng.choice(cpvs, M)
approch = pd.DataFrame({
    "code": [f"APP-{k}" for k in range(M)],
    "libelle": [f"Projet d'achat {c[:2]} {k}" for k, c in enumerate(a_cpv)],
    "statut": "Publié",
    "description": "",
    "siren_de_l_entite_acheteuse": [buyers[i][:9] for i in ab],
    "categorie_d_achat": rng.choice(["Travaux", "Services", "Fournitures"], M),
    "code_s_cpv": [f"{c}|{rng.choice(cpvs)}" for c in a_cpv],
    "date_previsionnelle_de_publication": (pd.Timestamp("2026-12-01") + pd.to_timedelta(rng.integers(0, 200, M), unit="D")).strftime("%Y-%m-%d"),
    "date_cible_de_remise_des_offres": (pd.Timestamp("2027-01-15") + pd.to_timedelta(rng.integers(0, 200, M), unit="D")).strftime("%Y-%m-%d"),
    "type_de_procedure": rng.choice(["Appel d'offres ouvert", "Procédure adaptée", "Procédure avec négociation"], M),
    "lien_vers_la_consultation": "https://example.org/consultation",
    "montant_estime_du_marche": rng.choice(["0 - 40k€", "40k - 100k€", "100k - 500k€", "500k - 1M€", "1M - 5M€", "+ 100M€"], M),
    "duree_previsionnelle_du_marche": rng.choice(["12", "24 mois", "3 ans", "48"], M),
    "departement_s_d_execution_du_marche": [f"{rng.choice(depts)}|{rng.choice(depts)}" for _ in range(M)],
    "considerations_sociales": rng.choice(["Oui", "Non"], M),
    "considerations_environnementales": rng.choice(["Oui", "Non"], M),
})
approch.to_parquet(RAW / "approch.parquet", index=False)
print(f"fake data: {len(decp):,} contracts, {len(approch):,} upcoming purchases in {RAW}")
