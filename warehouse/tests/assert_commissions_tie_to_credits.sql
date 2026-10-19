-- Every credited dollar (and every clawback) appears in exactly one statement month.
select s.rep_id, s.ytd_credited_arr, c.credited
from (select rep_id, sum(new_arr + expansion_arr) as ytd_credited_arr from {{ ref('fct_commission_statement_monthly') }} group by rep_id) s
join (select rep_id, sum(case when not is_clawback then credited_arr else 0 end) as credited
      from {{ ref('int_sales_credits') }} group by rep_id) c using (rep_id)
where s.ytd_credited_arr <> c.credited
