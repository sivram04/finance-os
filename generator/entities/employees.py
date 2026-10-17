"""Employees per the headcount plan (raw_payroll).

Each plan row starts with `start` people hired before the window and hires evenly up to `end` by the
last month. A few random leavers are replaced 30 days after they go.
"""
from datetime import date, timedelta
from decimal import Decimal


def build_employees(cfg, rng):
    start, end = cfg["window"]["start"], cfg["window"]["end"]
    span = (end - start).days
    employees = []

    def add(plan, hire_date):
        lo, hi = plan["salary"]
        employees.append({
            "employee_id": f"E{len(employees) + 1:03d}",
            "employee_name": f"Employee {len(employees) + 1:03d}",
            "department_id": plan["department"],
            "function": plan["function"],
            "title": plan["title"],
            "hire_date": hire_date,
            "termination_date": None,
            "annual_salary": Decimal(rng.randint(lo // 1000, hi // 1000) * 1000),
        })

    for plan in cfg["headcount_plan"]:
        for _ in range(plan["start"]):
            add(plan, date(2024, 1, 1) + timedelta(days=rng.randint(0, 360)))
        new = plan["end"] - plan["start"]
        for k in range(1, new + 1):
            add(plan, start + timedelta(days=int(span * k / (new + 1))))

    plans = {(p["department"], p["function"]): p for p in cfg["headcount_plan"]}
    for e in rng.sample(employees, cfg["terminations"]):
        e["termination_date"] = start + timedelta(days=rng.randint(60, span - 90))
        add(plans[(e["department_id"], e["function"])], e["termination_date"] + timedelta(days=30))
    return employees
