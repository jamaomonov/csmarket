"""``/api/v1`` — public API package.

Deliberately empty: module routes and dependencies import ``csmarket.api.v1.deps``, and
importing a submodule runs this file first. A router that imports those modules here
would close a cycle back to them. Routers are mounted in :mod:`csmarket.api.v1.router`.
"""
