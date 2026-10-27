"""What other modules may import from ``referrals``."""

from __future__ import annotations

from csmarket.modules.referrals.models import (
    ReferralAttribution,
    ReferralPartner,
    ReferralReward,
    ReferralVisitDay,
)

__all__ = ["ReferralAttribution", "ReferralPartner", "ReferralReward", "ReferralVisitDay"]
