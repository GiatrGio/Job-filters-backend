-- 0006_filter_kind.sql — split filters into two kinds.
--
-- Until now every filter was treated as a boolean criterion. In practice
-- users also write information-extraction queries — "What languages are
-- required?", "List the main skills" — which the boolean true/false/null
-- model handles awkwardly (the LLM tends to set pass=false because the
-- description doesn't literally satisfy a question). The two kinds:
--
--   - 'criterion'  → boolean filter. Result: pass ∈ {true,false,null}
--                    + ≤15-word evidence quote.
--   - 'question'   → info-extraction. Result: pass=null + a concise
--                    answer (≤30 words) drawn from the description.
--
-- The kind is set at filter-validation time (the LLM classifies the
-- filter as part of its quality check), stored here, and passed to the
-- evaluator on every /evaluate call so the prompt can branch per filter.
--
-- The default is 'criterion' so any pre-existing rows backfill cleanly
-- and any client that doesn't yet send `kind` keeps working unchanged.

alter table public.filters
    add column if not exists kind text not null default 'criterion'
    check (kind in ('criterion', 'question'));
