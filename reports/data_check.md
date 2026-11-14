# Data check

## Past contracts (DECP)

- contracts: 1,825,258
- contracts with an implausible year (before 2015 or in the future): 11,125 (ignored below)
- `offresrecues` usable (1–200): 42.3 %
- single-bid rate among usable rows: 22.9 %
- `offresrecues` = 0 or missing: 57.7 %

### Contracts and single-bid rate by year

- 2015: 11 contracts, 54.5 % single bid
- 2016: 48 contracts, 37.5 % single bid
- 2017: 77 contracts, 36.4 % single bid
- 2018: 170 contracts, 44.7 % single bid
- 2019: 2,091 contracts, 12.8 % single bid
- 2020: 29,506 contracts, 11.4 % single bid
- 2021: 40,891 contracts, 13.1 % single bid
- 2022: 48,329 contracts, 17.7 % single bid
- 2023: 68,003 contracts, 22.3 % single bid
- 2024: 234,069 contracts, 25.6 % single bid
- 2025: 212,833 contracts, 24.5 % single bid
- 2026: 130,708 contracts, 23.5 % single bid

### By procedure (canonical)

- adaptee: 351,544 contracts, 21.3 % single bid
- ouvert: 255,623 contracts, 17.7 % single bid
- NA: 89,679 contracts, 15.8 % single bid
- sans_pub: 40,747 contracts, 82.5 % single bid  ← excluded from training
- negociee: 17,390 contracts, 20.1 % single bid
- restreint: 11,144 contracts, 36.4 % single bid
- dialogue: 609 contracts, 12.6 % single bid

Raw procedure labels (check they map correctly in `procedure_canon`):
- `Procédure adaptée`: 935,199
- `Appel d'offres ouvert`: 609,955
- `Marché passé sans publicité ni mise en concurrence préalable`: 49,616
- `Procédure avec négociation`: 24,639
- `Appel d'offres restreint`: 21,633
- `Marché négocié sans publicité ni mise en concurrence préalable`: 18,046
- `Appel d offres ouvert`: 7,558
- `Procédure négociée avec mise en concurrence préalable`: 6,476
- `Procédure concurrentielle avec négociation`: 5,150
- `Marché public négocié sans publicité ni mise en concurrence préalable`: 5,039
- `Dialogue compétitif`: 1,799
- `Appel d offres restreint`: 375

### Feature fill rates

- cpv_div: 100.0 %
- amount_band: 98.0 %
- duration_bin: 99.5 %
- dept: 95.8 %
- buyer_siren: 100.0 %
- awards with a company SIREN: 2,068,701 rows, 160,980 companies

## Upcoming purchases (APProch)

- rows: 10,569
- with a publication or deadline date from today on: 4,146
- cpv_div: 89.1 %
- amount_band: 100.0 %
- duration_bin: 100.0 %
- dept: 91.2 %
- buyer_siren: 99.9 %
- procedure_c: 11.5 %
- upcoming purchases whose buyer has past contracts: 66.9 %

APProch raw procedure labels:
- `Appel d'offres ouvert`: 941
- `Procédure négociée sans publicité ni mise en concurrence préalables`: 92
- `Procédure avec négociation - Candidature`: 58
- `Procédure adaptée > 90 000`: 23
- `Système d'Acquisition Dynamique`: 22
- `Appel d'offres restreint - Candidature`: 15
- `Procédure adaptée ouverte`: 15
- `Concours restreint - Candidature`: 11
- `Conventions et procédures autres`: 9
- `Procédure adaptée < 90 000`: 8

APProch duration examples (check `duration_months` parses them): `48`, `8`, `12`, `24`, `6`, `36`, `3`, `2`
APProch amount bands: `40k - 100k€`, `500k - 1M€`, `1M - 5M€`, `100k - 500k€`, `0 - 40k€`, `10M - 50M€`, `5M - 10M€`, `50M - 100M€`, `+ 100M€`

## Verdict

Training window: 2023–2024 (285,578 labelled contracts), test: 2025 onwards (320,228). Share of contracts with a usable bid count: 42.3 %.
GO. Buyer overlap 66.9 %. Mention in the limits that only contracts with a reported number of bids (42.3 %) are used.