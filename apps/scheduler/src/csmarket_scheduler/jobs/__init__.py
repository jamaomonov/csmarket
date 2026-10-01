"""Periodic jobs. One module per job, each exposing ``register(scheduler)``.

M1: ``purge_refresh_tokens`` (daily, first run after 300 s).
M2: ``fx_refresh`` (hourly, first run after 20 s), ``skins_catalog_import`` (daily, first run after 120 s), ``skins_price_sync`` (5 min).
M3: ``topup_expiry`` (5 min, first run after 140 s).
M4: ``expire_pending`` (1 min), ``trades_reconcile`` (2–3 min), ``protection_watch`` (daily),
``history_audit`` (daily). Long-period jobs use ``startup.first_run_after`` with staggered
delays so a deploy does not fire them all at once.
"""
