"""Furniture market decision system.

A warehouse-backed replacement for the one-shot selection report. Three layers,
deliberately decoupled:

    collectors  ->  warehouse  ->  decision
    (metered,       (SQLite,       (deterministic scoring +
     bounded)        monthly)       model narrative over evidence)

The split that matters most is ingest vs render. Ingest spends vendor credits and
writes rows; render reads rows and calls the model. A model outage therefore costs
nothing and can be retried forever, which is why this package has no sweep cache:
the database is the cache.
"""
from __future__ import annotations

__all__ = ["fields", "store", "taxonomy"]
