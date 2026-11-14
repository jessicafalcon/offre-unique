"""Embed every distinct title (DECP contracts since MIN_YEAR + APProch + BOAMP) with Featherless.

    python experiments/embed_titles.py [--dim 256] [--batch 256] [--workers 4]

Model: Qwen/Qwen3-Embedding-0.6B (1024 dims, Matryoshka-trained: the first `dim` dims are kept and
re-normalised). Output, reused by text_auc.py and matching_recall.py:
    experiments/cache/emb_titles.npy      float16 [n_titles, dim], L2-normalised
    experiments/cache/emb_titles.parquet  key (normalised title) -> row
Resumable: finished batches are kept in experiments/cache/emb_parts/.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

from _shared import CACHE, featherless, guard, mem_gb
from common import CLEAN, MIN_YEAR

MODEL = "Qwen/Qwen3-Embedding-0.6B"


def title_key(s: pd.Series) -> pd.Series:
    """Normalised title used as the join key everywhere in the experiments."""
    return s.fillna("").astype(str).str.strip().str.lower().str.replace(r"\s+", " ", regex=True).str.slice(0, 400)


def all_titles() -> pd.Series:
    c = pd.read_parquet(CLEAN / "contracts.parquet", columns=["objet", "year"])
    keys = [title_key(c.loc[c["year"] >= MIN_YEAR, "objet"])]
    del c
    for name in ("approch", "boamp"):
        p = CLEAN / f"{name}.parquet"
        if p.exists():
            cols = [x for x in ("libelle", "objet_du_marche", "objet", "intitule") if x in pd.read_parquet(p).columns]
            for col in cols[:1]:
                keys.append(title_key(pd.read_parquet(p, columns=[col])[col]))
    k = pd.concat(keys, ignore_index=True)
    k = k[k != ""].drop_duplicates().sort_values().reset_index(drop=True)
    return k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dim", type=int, default=256)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    keys = all_titles()
    n = len(keys)
    print(f"{n:,} distinct titles · mem {mem_gb():.2f} GB", flush=True)
    parts = CACHE / "emb_parts"
    parts.mkdir(exist_ok=True)
    meta = parts / "meta.json"
    if meta.exists() and json.loads(meta.read_text()) != {"n": n, "dim": a.dim, "batch": a.batch, "model": MODEL}:
        raise SystemExit("emb_parts/ was made with other settings: delete it first")
    meta.write_text(json.dumps({"n": n, "dim": a.dim, "batch": a.batch, "model": MODEL}))

    batches = [i for i in range(0, n, a.batch) if not (parts / f"{i:08d}.npy").exists()]
    print(f"{len(batches):,} batches to do", flush=True)
    client = featherless()
    cost = 0.0
    t0 = time.time()

    def run(i: int):
        texts = keys.iloc[i:i + a.batch].tolist()
        for attempt in range(6):
            try:
                r = client.embeddings.create(model=MODEL, input=texts)
                break
            except Exception as e:  # rate limit or transient error: back off
                if attempt == 5:
                    raise
                time.sleep(2 ** attempt)
        e = np.asarray([d.embedding for d in r.data], dtype=np.float32)[:, :a.dim]
        e /= np.linalg.norm(e, axis=1, keepdims=True) + 1e-12
        np.save(parts / f"{i:08d}.npy", e.astype(np.float16))
        return float(getattr(r.usage, "cost", 0) or 0)

    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run, i) for i in batches]
        for k, f in enumerate(as_completed(futs), 1):
            cost += f.result()
            if k % 200 == 0 or k == len(futs):
                el = time.time() - t0
                print(f"  {k:,}/{len(futs):,} batches · {el / 60:.1f} min · ~{el / k * (len(futs) - k) / 60:.0f} min left"
                      f" · ${cost:.3f} · mem {guard('embedding'):.2f} GB", flush=True)

    out = np.zeros((n, a.dim), dtype=np.float16)
    for i in range(0, n, a.batch):
        out[i:i + a.batch] = np.load(parts / f"{i:08d}.npy")
    np.save(CACHE / "emb_titles.npy", out)
    pd.DataFrame({"key": keys, "row": np.arange(n)}).to_parquet(CACHE / "emb_titles.parquet", index=False)
    print(f"saved {n:,} x {a.dim} embeddings · total cost this run ${cost:.3f}", flush=True)


if __name__ == "__main__":
    main()
