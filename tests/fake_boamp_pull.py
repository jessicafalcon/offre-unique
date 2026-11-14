"""Run src/pull_boamp.py against a simulated BOAMP API (for testing without network).

    python tests/fake_boamp_pull.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pull_boamp  # noqa: E402

rng = np.random.default_rng(7)
decp = pd.read_parquet(ROOT / "data" / "raw" / "decp.parquet")
buyers = decp["acheteur_id"].astype(str).unique()
cpvs = decp["codeCPV"].astype(str).unique()
N = 730
natures = rng.choice(["Avis de marché", "Avis de marché", "Avis de marché", "Rectificatif", "Résultat de marché"], N)
records = []
for i in range(N):
    b = rng.choice(buyers)
    has_cpv, has_siret = rng.random() < 0.85, rng.random() < 0.84
    donnees = {"EFORMS": {"ContractNotice": {
        "cac:ContractingParty": {"cbc:CompanyID": b if has_siret else "", "Tel": "0145678901", "CP": "75011"},
        "cac:ProcurementProject": {"cbc:ItemClassificationCode": {"@listName": "cpv", "#text": rng.choice(cpvs) if has_cpv else ""}},
        "dates": "2026-11-13"}}}
    records.append({
        "idweb": f"26-{100000 + i}", "objet": f"Avis {i}", "nomacheteur": f"Mairie {i % 50}",
        "code_departement": [str(rng.choice(["75", "93", "77", "69"]))],
        "datelimitereponse": "2026-12-15T10:00:00+00:00", "dateparution": "2026-11-13",
        "nature_libelle": natures[i], "type_marche": ["SERVICES"], "procedure_libelle": "Procédure ouverte",
        "url_avis": f"https://www.boamp.fr/pages/avis/?q=idweb:26-{100000 + i}", "famille_libelle": "Marchés",
        "donnees": json.dumps(donnees),
    })


class Resp:
    def __init__(self, payload):
        self.status_code, self._p, self.text = 200, payload, ""

    def json(self):
        return self._p


def fake_get(url, params=None, timeout=None):
    off, lim = params["offset"], params["limit"]
    return Resp({"total_count": N, "results": [dict(r) for r in records[off:off + lim]]})


pull_boamp.requests.get = fake_get
pull_boamp.main()
