"""Shared building blocks for the redesigned Offre unique pages (webdesign/).

Every page imports from here, so the main app can adopt one piece at a time:
    taxonomy.py  pictos, labels and colours (company size, sector, buyer kind, amount, chance of a single bid)
    data.py      low-RAM data access on top of Jessica's src/ (never loads the full awards file)
    charts.py    ECharts helpers with the shared style
    ui.py        small HTML/CSS components (cards, chips, badges)
"""
