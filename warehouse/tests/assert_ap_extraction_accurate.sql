{{ config(severity = 'error' if var('ap_backend') == 'text' else 'warn') }}
-- The rules extractor must read every field of every document exactly. For the Grok backend this is a
-- warning: the accuracy table is its eval score, not a build blocker.
select *
from {{ ref('fct_ap_extraction_accuracy') }}
where accuracy < 1
