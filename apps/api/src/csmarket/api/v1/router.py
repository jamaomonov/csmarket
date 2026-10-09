"""``/api/v1`` — public API mount.

Modules register their routers here (not in the package ``__init__``, which
``api/v1/deps.py`` importers run first — see ``tests/unit/test_import_order.py``).
Keep the imports alphabetical for diff readability. A module whose routes import
``auth.api`` while ``auth`` imports its ``api`` (``users``) is mounted from its
``routes`` module directly — see ``modules/users/api.py`` (``admin`` likewise).
"""

from __future__ import annotations

from fastapi import APIRouter

from csmarket.modules.admin.api_keys_routes import router as admin_api_keys_router
from csmarket.modules.admin.audit_routes import router as admin_audit_router
from csmarket.modules.admin.dashboard_routes import router as admin_dashboard_router
from csmarket.modules.admin.orders_routes import router as admin_orders_router
from csmarket.modules.admin.payments_routes import router as admin_payments_router
from csmarket.modules.admin.routes import router as admin_router
from csmarket.modules.admin.users_routes import router as admin_users_router
from csmarket.modules.auth.api import router as auth_router
from csmarket.modules.click.routes import router as click_router
from csmarket.modules.notifications.routes_dev import router as notifications_dev_router
from csmarket.modules.orders.dev_routes import router as orders_dev_router
from csmarket.modules.orders.routes import me_router as my_orders_router
from csmarket.modules.orders.routes import router as orders_router
from csmarket.modules.payme.routes import router as payme_router
from csmarket.modules.payments.dev_routes import router as payments_dev_router
from csmarket.modules.payments.routes import router as payments_router
from csmarket.modules.payments.routes import wallet_router as topups_router
from csmarket.modules.public_api.offer_check_route import router as public_offer_check_router
from csmarket.modules.public_api.routes import router as public_api_router
from csmarket.modules.public_api.site_routes import router as api_key_router
from csmarket.modules.public_api.tradelink_route import router as public_tradelink_router
from csmarket.modules.realtime.routes import router as realtime_router
from csmarket.modules.sales.admin_routes import router as sales_admin_router
from csmarket.modules.sales.cards_routes import router as payout_cards_router
from csmarket.modules.sales.routes import router as sales_router
from csmarket.modules.skins.admin_routes import router as skins_admin_router
from csmarket.modules.skins.dev_routes import router as skins_dev_router
from csmarket.modules.skins.pricing_routes import router as skins_pricing_router
from csmarket.modules.skins.routes import router as skins_router
from csmarket.modules.skins.seo_routes import router as skins_seo_router
from csmarket.modules.skinslink.routes import router as skinslink_router
from csmarket.modules.users.routes import router as users_router
from csmarket.modules.users.routes_email import me_router as users_email_me_router
from csmarket.modules.users.routes_email import router as users_email_router
from csmarket.modules.uzum.routes import router as uzum_router
from csmarket.modules.wallet.routes import router as wallet_router

router = APIRouter()
router.include_router(admin_router)
router.include_router(admin_users_router)
router.include_router(admin_api_keys_router)
router.include_router(admin_payments_router)
router.include_router(admin_audit_router)
router.include_router(admin_dashboard_router)
router.include_router(admin_orders_router)
router.include_router(sales_admin_router)
router.include_router(api_key_router)
router.include_router(public_api_router)
router.include_router(public_tradelink_router)
router.include_router(public_offer_check_router)
router.include_router(auth_router)
router.include_router(click_router)
router.include_router(notifications_dev_router)
router.include_router(orders_router)
router.include_router(my_orders_router)
router.include_router(orders_dev_router)
router.include_router(payme_router)
router.include_router(payments_dev_router)
router.include_router(payments_router)
router.include_router(payout_cards_router)
router.include_router(sales_router)
router.include_router(realtime_router)
router.include_router(skins_admin_router)
router.include_router(skins_pricing_router)
router.include_router(skins_dev_router)
# /skins/seo/* must precede /skins/{slug}, which would otherwise swallow it.
router.include_router(skins_seo_router)
router.include_router(skins_router)
router.include_router(skinslink_router)
router.include_router(users_router)
router.include_router(users_email_me_router)
router.include_router(users_email_router)
router.include_router(uzum_router)
router.include_router(wallet_router)
# /wallet/topups* is ``payments``' (``wallet`` never imports ``payments``).
router.include_router(topups_router)
