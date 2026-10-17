"""Manifest of injected anomalies (FR-1.4), so tests can confirm each one is detected."""


def build_manifest(cfg):
    return [
        {
            "anomaly_id": a["anomaly_id"],
            "module": a["module"],
            "kind": a["kind"],
            "entity_id": a["customer_id"],
            "start_date": a["start"],
            "description": a["description"],
            "expected_detection": a["expected_detection"],
        }
        for a in cfg.get("anomalies", [])
    ]
