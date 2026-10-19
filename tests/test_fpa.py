"""FP&A calculators: NPV / IRR / payback and the runway sensitivity grid."""
from finance_os import fpa


def test_npv_irr_and_payback_agree_with_hand_math():
    flows = [-1000, 500, 500, 500]
    assert round(fpa.npv(0.10, flows), 2) == 243.43
    assert abs(fpa.npv(fpa.irr(flows), flows)) < 1e-4 and round(fpa.irr(flows), 4) == 0.2338
    assert fpa.payback(flows) == 2.0
    case = fpa.business_case(1000, [500, 500, 500], 0.10)
    assert case["npv"] == 243.43 and case["verdict"].startswith("Invest")


def test_no_irr_without_a_sign_change_and_no_payback_when_it_never_pays():
    assert fpa.irr([100, 100]) is None
    assert fpa.payback([-1000, 100, 100]) is None
    assert fpa.business_case(1000, [100, 100], 0.10)["verdict"].startswith("Don't")


def test_runway_grid_gets_longer_with_growth_and_with_cuts():
    t = fpa.runway_sensitivity(1_000_000, 100_000, 0.3, 200_000, [0, 0.05], [-0.2, 0], 0.0)
    flat, fast = t
    assert flat["opex +0%"] < flat["opex -20%"]
    assert flat["opex +0%"] == 8          # burn 130K a month on $1M
    assert fast["opex +0%"] == "60+" or fast["opex +0%"] > flat["opex +0%"]


def test_every_sales_led_customer_is_a_won_deal_and_no_self_serve_in_the_crm():
    from finance_os.generator.__main__ import load_config
    from finance_os.generator.entities.customers import build_customers
    from finance_os.generator.events.pipeline import build_pipeline
    import random
    cfg = load_config()
    customers, _ = build_customers(cfg, random.Random(cfg["seed"]))
    opps = build_pipeline(cfg, customers)
    won = {o["customer_id"] for o in opps if o["stage"] == "closed_won"}
    assert won == {c["customer_id"] for c in customers if c["segment"] in ("mid_market", "enterprise")}
    assert all(o["segment"] != "self_serve" for o in opps)
    assert all(o["created_date"] <= o["close_date"] for o in opps if o["stage"].startswith("closed"))
    lost = sum(o["stage"] == "closed_lost" for o in opps)
    assert 0.15 < len(won) / (len(won) + lost) < 0.40          # a believable win rate
