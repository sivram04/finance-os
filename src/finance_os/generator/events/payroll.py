"""Monthly pay runs with a line-item payroll register (raw_payroll), like an ADP or Gusto register export.

Per employee per run, pay is prorated by days employed in the month, then broken into register lines:
  earning            REG (salary)
  employee_deduction 401K_EE (pre-tax), MEDICAL_EE
  employee_tax       FIT (federal withholding), SIT (state), SS_EE, MEDICARE_EE
  employer_tax       SS_ER, MEDICARE_ER, FUTA, SUTA
  employer_benefit   MEDICAL_ER, 401K_MATCH
  net_pay            what lands in the employee's bank account
Social Security, FUTA and SUTA stop at their annual wage bases (tracked year to date per employee), so employer
tax is not a flat rate: it falls late in the year for high earners, as in a real register.

pay_lines (gross / employer tax / employer benefits per employee and run) is the register summed, kept for the
models that work at that grain. `register_lines` is shared with the live simulator so live payroll is computed
the same way.
"""
import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")
RATES = {
    "SS": Decimal("0.062"), "MEDICARE": Decimal("0.0145"), "FUTA": Decimal("0.006"), "SUTA": Decimal("0.027"),
    "SIT": Decimal("0.05"), "401K_EE": Decimal("0.06"), "401K_MATCH": Decimal("0.04"),
}
WAGE_BASE = {"SS": {2025: Decimal("176100"), 2026: Decimal("184500"), 2027: Decimal("190800")},
             "FUTA": Decimal("7000"), "SUTA": Decimal("9000")}
MEDICAL_EE, MEDICAL_ER = Decimal("180.00"), Decimal("770.00")   # per month; ER + 401k match ≈ the old $950 benefits
FIT_BRACKETS = [(Decimal("1000"), Decimal("0.10")), (Decimal("4000"), Decimal("0.12")), (Decimal("9000"), Decimal("0.22")),
                (Decimal("17000"), Decimal("0.24")), (None, Decimal("0.32"))]  # monthly taxable wages, simplified


def _cents(x):
    return x.quantize(CENTS, rounding=ROUND_HALF_UP)


def _capped(amount, ytd, base):
    """The part of this period's wages still under the annual wage base."""
    return max(min(amount, base - ytd), Decimal(0))


def _fit(taxable):
    tax, floor = Decimal(0), Decimal(0)
    for top, rate in FIT_BRACKETS:
        if top is None or taxable <= top:
            return tax + (taxable - floor) * rate
        tax += (top - floor) * rate
        floor = top
    return tax


def register_lines(gross, factor, year, ytd):
    """Register lines for one employee's pay: [(line_type, code, amount)]. ytd = wages paid earlier this year
    (before this run); the caller adds `gross` to it afterwards."""
    ee_401k = _cents(gross * RATES["401K_EE"])
    med_ee, med_er = _cents(MEDICAL_EE * factor), _cents(MEDICAL_ER * factor)
    taxable = gross - ee_401k - med_ee
    ss_base = WAGE_BASE["SS"].get(year, max(WAGE_BASE["SS"].values()))
    ss_wages = _capped(gross, ytd, ss_base)
    lines = [
        ("earning", "REG", gross),
        ("employee_deduction", "401K_EE", ee_401k),
        ("employee_deduction", "MEDICAL_EE", med_ee),
        ("employee_tax", "FIT", _cents(_fit(taxable))),
        ("employee_tax", "SIT", _cents(taxable * RATES["SIT"])),
        ("employee_tax", "SS_EE", _cents(ss_wages * RATES["SS"])),
        ("employee_tax", "MEDICARE_EE", _cents(gross * RATES["MEDICARE"])),
        ("employer_tax", "SS_ER", _cents(ss_wages * RATES["SS"])),
        ("employer_tax", "MEDICARE_ER", _cents(gross * RATES["MEDICARE"])),
        ("employer_tax", "FUTA", _cents(_capped(gross, ytd, WAGE_BASE["FUTA"]) * RATES["FUTA"])),
        ("employer_tax", "SUTA", _cents(_capped(gross, ytd, WAGE_BASE["SUTA"]) * RATES["SUTA"])),
        ("employer_benefit", "MEDICAL_ER", med_er),
        ("employer_benefit", "401K_MATCH", _cents(gross * RATES["401K_MATCH"])),
    ]
    withheld = sum(a for t, _, a in lines if t in ("employee_tax", "employee_deduction"))
    lines.append(("net_pay", "NET", gross - withheld))
    return [(t, c, a) for t, c, a in lines if a != 0 or t in ("earning", "net_pay")]


def summarize(lines):
    """(gross, employer_tax, employer_benefits, employee_withholding_taxes, employee_deductions, net)"""
    s = lambda t: sum((a for lt, _, a in lines if lt == t), Decimal(0))  # noqa: E731
    return s("earning"), s("employer_tax"), s("employer_benefit"), s("employee_tax"), s("employee_deduction"), s("net_pay")


def build_payroll(cfg, employees):
    start, end = cfg["window"]["start"], cfg["window"]["end"]
    runs, lines, register = [], [], []
    ytd = {}
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        days = calendar.monthrange(y, m)[1]
        first, last = date(y, m, 1), date(y, m, days)
        run_id = f"PR-{y}{m:02d}"
        runs.append({"pay_run_id": run_id, "period_start": first, "period_end": last, "pay_date": last})
        for e in employees:
            active_from = max(e["hire_date"], first)
            active_to = min(e["termination_date"] or last, last)
            if active_from > active_to:
                continue
            factor = Decimal((active_to - active_from).days + 1) / Decimal(days)
            gross = _cents(e["annual_salary"] / 12 * factor)
            key = (e["employee_id"], y)
            reg = register_lines(gross, factor, y, ytd.get(key, Decimal(0)))
            ytd[key] = ytd.get(key, Decimal(0)) + gross
            for n, (t, code, amount) in enumerate(reg, 1):
                register.append({"pay_run_id": run_id, "employee_id": e["employee_id"], "department_id": e["department_id"],
                                 "line_no": n, "line_type": t, "code": code, "amount": amount})
            g, er_tax, er_ben, *_ = summarize(reg)
            lines.append({"pay_run_id": run_id, "employee_id": e["employee_id"], "department_id": e["department_id"],
                          "gross_pay": g, "employer_tax": er_tax, "benefits": er_ben})
        y, m = y + (m == 12), m % 12 + 1
    return runs, lines, register
