# Plan group names enum for use across the codebase


PRO_GROUP = 'pro'
PREMIUM_GROUP = 'premium'
BASIC_GROUP = 'basic'
FREE_GROUP = 'free'
UNSUBSCRIBED_GROUP = 'unsubscribed'

SUBSCRIPTION_GROUPS = [
    PRO_GROUP,
    PREMIUM_GROUP,
    BASIC_GROUP,
    FREE_GROUP,
]

ALL_GROUPS = SUBSCRIPTION_GROUPS + [
    UNSUBSCRIBED_GROUP,
]

