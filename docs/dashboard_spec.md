# Workspace dashboards: what an experienced finance VP expects, page by page

Each page answers the questions a VP of Finance or Controller with 20 years of experience asks of that area,
in the order they ask them. Layout follows common practice ([Metabase][mb], [Keboola][kb]): KPI cards first, then
trends, then breakdowns that cross-filter, and the detail table last. Every number has a comparison (terms, target,
last period, plan or benchmark), and every chart supports a decision (who to chase, what to cut, what to escalate).

**Cross-filtering.** Clicking a slice, bar or segment filters the whole page: KPI cards, the other charts and the
tables. A filter bar shows what is applied, and you can clear it with one click. A chart never filters itself (it
highlights the selection), so you can still see the share the selection holds.

---

## 1. Receivables: "will the cash come in, and who do we chase?"

Sources: [Emagia][em], [Gaviti][ga], [Tesorio][te], [Upflow][up]. Read DSO next to CEI and terms, never alone.

| Question | Answer on the page |
|---|---|
| How much is owed to us, and how much is late? | KPIs: open AR, past due $ and % of open AR |
| Are we collecting worse than before? | KPIs: DSO vs 30-day terms, CEI (3 months), average days delinquent. Trend: DSO and CEI over 12 months |
| Where is the late money? | Donut: open AR by aging bucket. Bar: open AR by segment (both cross-filter) |
| Who do we call first? | Bar: top customers by open balance, past due stacked (click a customer to filter) |
| What's blocked? | KPI: disputed $. Table: disputes and holds with owner and action |
| When does the cash land? | Bar: expected customer receipts by week (13-week forecast) |
| Detail | Open invoices: customer, segment, bucket, due date, days late, recommended action |

## 2. Budget vs actual: "are we on plan, and why not?"

Sources: [Metabase][mb], [Keboola][kb]. Normalize signs: favorable is green for revenue *and* costs.

| Question | Answer |
|---|---|
| Are we on plan this month / year to date / full year? | KPIs: revenue, opex, EBITDA vs budget (fav/unfav), YTD variance, FY forecast vs budget |
| How did we get from budget to actual? | Waterfall: budget EBITDA → revenue, COGS, each opex rollup → actual EBITDA |
| Which departments are off? | Bar: variance by department (click to filter) |
| Is it a trend or a one-off? | Trend: actual vs budget by month, 12 months |
| Who owns it and what's the explanation? | Table: material variances (beyond threshold) with owner, driver and the transactions behind it |

## 3. Tech spend (FinOps): "is spend under control relative to usage?"

Sources: [Flexera][fx], [Holori][ho], [Cloudaware][cw]. Show utilization and coverage together; the unit cost trend
matters more than total spend.

| Question | Answer |
|---|---|
| What did we spend, versus last month and versus plan? | KPIs: spend this month, change vs last month, next-month forecast |
| Is spend growing faster than usage? | KPI and trend: cost per audio hour; spend vs audio hours, indexed |
| Are we paying for capacity we don't use? | KPI and trend: GPU commit utilization against an 80% target; shortfall $ |
| Who is spending it? | Donut: by vendor; bar: by team (cross-filter); tagging coverage |
| What's coming up? | Contract renewals with notice dates; 3-month forecast |

## 4. AP inbox: "are we paying the right bills at the right time?"

Sources: [Corpay][cp], [Spendesk][sp]. Weekly operational view, not a monthly report.

| Question | Answer |
|---|---|
| How much do we owe, and when is it due? | KPIs: open AP, due in the next 14 days; bar: due by week |
| Is the process healthy? | KPIs: touchless (auto-approved) rate, exception rate, DPO vs terms |
| What's stuck and why? | Donut: exceptions by reason (click to filter); bar: exceptions by vendor |
| Are we leaving money on the table? | KPI: early-pay discounts captured vs available |
| Detail | Bills needing review, with the reasons and a one-click assistant decision |

## 5. Close: "will we close on time, and what's blocking it?"

Source: close-management practice (T+1 to T+3, owner, status, blocker).

| Question | Answer |
|---|---|
| Where are we in the close? | KPIs: workday vs plan, tasks complete %, overdue tasks, reconciliations passing |
| Who is behind? | Bar: open and overdue tasks by owner (click to filter) |
| What's left on the critical path? | Timeline: tasks by workday and status |
| Are the numbers ready? | Accruals, prepaid amortization, ASC 606 adjustment, recon status |

## 6. Projects: "which projects lose money or cash?"

Sources: [Teamwork][tw], [Factor][fa] (WIP: earned vs billed), earned value (CPI, EAC).

| Question | Answer |
|---|---|
| Is the portfolio profitable? | KPIs: contract value, EAC vs budget, unbilled WIP, projects over budget |
| Which projects are over budget? | Bar: EAC as % of budget per project, with a 100% line (click to filter) |
| Are we billing what we've earned? | Bar: earned vs billed per project (under- and overbilling) |
| Will federal funding run out? | Funding used per contract against 75% and 90% notice lines |
| What needs action? | Exceptions: unbilled milestones, rate mismatches, bills without PO |

## 7. Revenue & margins, 8. Billing, 9. Commissions, 10. Capital, 11. Tax & FX, 12. Trust, 13. Alerts

Same pattern; specified when each page is built.

[mb]: https://www.metabase.com/dashboards/budget-vs-actuals
[kb]: https://www.keboola.com/use-case/budget-vs-actual-variance-analysis-management-reporting
[em]: https://www.emagia.com/blog/building-an-ar-dashboard/
[ga]: https://gaviti.com/modern-financial-dashboards-ar-metrics/
[te]: https://tesorio.com/resource-ar-dashboard
[up]: https://upflow.io/blog/ar-metrics/financial-dashboard
[fx]: https://www.flexera.com/blog/finops/finops-metrics-vs-performance/
[ho]: https://holori.com/finops-kpis-and-metrics-what-to-measure-and-when/
[cw]: https://docs.cloudaware.com/DOCS/finops-kpis-bechnmarking
[cp]: https://www.corpay.com/resources/blog/accounts-payable-kpis
[sp]: https://www.spendesk.com/blog/accounts-payable-kpis/
[tw]: https://www.teamwork.com/blog/financial-project-reports/
[fa]: https://factorapp.com/blog/accurate-wip-reports-that-improve-cash-flow
