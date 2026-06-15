-- 0013_dom_diagnostics_call_type.sql — allow 'dom_diagnostics' LLM calls.
--
-- Measure 3: when the extension's LinkedIn scraper fails or comes back partial,
-- it POSTs telemetry to /diagnostics/dom, which runs a diagnostic LLM analysis
-- and logs it to llm_calls so we can triage breakage in /admin. That requires a
-- third allowed call_type alongside the existing two.
--
-- The check constraint added inline in 0011 is auto-named
-- `llm_calls_call_type_check`; drop and recreate it with the widened set.

alter table public.llm_calls
    drop constraint if exists llm_calls_call_type_check;

alter table public.llm_calls
    add constraint llm_calls_call_type_check
    check (call_type in ('job_evaluation', 'filter_validation', 'dom_diagnostics'));
