from datetime import datetime, timezone

import pytz


def is_market_open(asset_class: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if asset_class == "CRYPTO":
        return True
    et = now.astimezone(pytz.timezone("US/Eastern"))
    wd, hm = et.weekday(), et.hour * 60 + et.minute
    if asset_class == "FOREX":
        if wd == 5:
            return False
        if wd == 6 and et.hour < 17:
            return False
        if wd == 4 and et.hour >= 17:
            return False
        return True
    if asset_class in ("STOCK", "INDEX", "COMMODITY"):
        return wd < 5 and 570 <= hm < 960
    return False


def metal_weekend_tag(asset_class: str, ts_ms: int) -> str | None:
    """Gold and silver perps keep trading on Saturday and Sunday. Tag those bars."""
    if asset_class != "SCALP_METAL":
        return None
    moment = datetime.fromtimestamp(ts_ms / 1000, timezone.utc)
    if moment.weekday() >= 5:
        return "METAL_WEEKEND"
    return None
