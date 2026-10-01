"""Domain modules.

Each module owns its own tables and exposes a narrow public interface via ``api.py``.
**Never** import internals (models, schemas, services) of one module from another;
call ``api.py``. Modules arrive by milestone: auth, users (M1); skins (M2); fx,
wallet, payments, click, payme, uzum (M3); orders, admin, notifications, realtime (M4).
"""
