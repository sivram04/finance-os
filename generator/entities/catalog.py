"""Products, price list and volume tiers, straight from config."""
from decimal import Decimal


def build_products(cfg):
    return [
        {
            "product_id": p["product_id"],
            "model": p["model"],
            "workload": p["workload"],
            "list_price_per_hour": Decimal(p["list_price_per_hour"]),
        }
        for p in cfg["products"]
    ]


def build_volume_tiers(cfg):
    return [
        {
            "tier": i + 1,
            "min_hours_month": t["min_hours_month"],
            "discount_pct": Decimal(t["discount_pct"]),
        }
        for i, t in enumerate(cfg["volume_tiers"])
    ]
