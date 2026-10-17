"""GPU job logs and daily cloud overhead lines (raw_infra).

GPU jobs: each usage row is served by 1–3 jobs; GPU seconds = audio hours × the model's
seconds-per-hour × noise (× the anomaly multiplier where one applies). Each model also
burns shared idle/warm-pool seconds per day, logged as jobs with no customer.
Cloud overhead: fixed $/day + $ per audio hour served that day, per configured line.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

COST_DP = Decimal("0.000001")


def build_gpu_jobs(cfg, usage, rng):
    model_of = {p["product_id"]: p["model"] for p in cfg["products"]}
    workload_of = {p["product_id"]: p["workload"] for p in cfg["products"]}
    shifts = {a["customer_id"]: a for a in cfg.get("anomalies", []) if a["kind"] == "streaming_shift"}
    shared_pct = Decimal(cfg["shared_gpu_pct"])

    jobs, seq = [], 0
    direct_seconds = defaultdict(int)  # (date, product_id) -> seconds

    def add(day, customer_id, product_id, seconds, env_label):
        nonlocal seq
        seq += 1
        model = model_of[product_id]
        jobs.append({
            "job_id": f"J{seq:08d}",
            "job_date": day,
            "customer_id": customer_id,
            "product_id": product_id,
            "model": model,
            "workload": workload_of[product_id],
            "gpu_type": cfg["gpu_profile"][model]["gpu_type"],
            "gpu_seconds": seconds,
            "region": cfg["region"],
            "label_team": "infra",
            "label_env": env_label,
        })

    for u in usage:
        profile = cfg["gpu_profile"][model_of[u["product_id"]]]
        mult = Decimal(1)
        shift = shifts.get(u["customer_id"])
        if shift and u["product_id"] == "stream" and u["usage_date"] >= shift["start"]:
            mult = Decimal(shift["gpu_seconds_multiplier"])
        total = u["audio_hours"] * profile["seconds_per_hour"] * mult * Decimal(rng.randint(90, 110)) / 100
        n = rng.randint(1, 3)
        for i in range(n):
            secs = int(total / n)
            if secs > 0:
                add(u["usage_date"], u["customer_id"], u["product_id"], secs, "prod")
                direct_seconds[(u["usage_date"], u["product_id"])] += secs

    for (day, product_id), secs in sorted(direct_seconds.items()):
        add(day, None, product_id, int(secs * shared_pct), "prod")
    return jobs


def build_cloud_costs(cfg, usage):
    hours_by_day = defaultdict(Decimal)
    for u in usage:
        hours_by_day[u["usage_date"]] += u["audio_hours"]

    rows = []
    day, end = cfg["window"]["start"], cfg["window"]["end"]
    while day <= end:
        for line in cfg["cloud_overhead"]:
            cost = Decimal(line["fixed"]) + Decimal(line["per_hour"]) * hours_by_day[day]
            rows.append({
                "usage_date": day,
                "service": line["service"],
                "sku": line["sku"],
                "label_team": line["team"],
                "label_env": line["env"],
                "cost": cost.quantize(COST_DP),
            })
        day += timedelta(days=1)
    return rows
