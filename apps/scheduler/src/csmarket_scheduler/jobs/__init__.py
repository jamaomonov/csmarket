"""Periodic jobs. One module per job, each exposing ``register(scheduler)``.

M2: ``skins_catalog_import`` (daily), ``skins_price_sync`` (5 min).
M4: ``expire_pending`` (1 min), ``trades_reconcile`` (2–3 min), ``protection_watch`` (daily),
``history_audit`` (daily). Long-period jobs use ``startup.first_run_after`` with staggered
delays so a deploy does not fire them all at once.
"""
