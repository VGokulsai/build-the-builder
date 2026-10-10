# Plan (10 Oct 2026, before the kit)

## Builder design
1. Baseline first: run the kit's sample builder, score it on the 13 practice customers. Every change must raise the pass count or it is reverted.
2. Read: strong model (Opus/Sonnet via claude-cli) turns the brief into a strict checklist JSON (identity questions, wrong-answer limit, what is forbidden before verification, third-party handling, allowed dates/holidays/business-day windows, amount limits, outcome table). Code validates it; re-read on gaps.
3. Build: code assembles the Freya workflow from the checklist with a tested template (steps, routes, tools). The model writes only prompt wording.
4. Date and money rules run as code inside the workflow (holidays, weekends, business days from `now`, minimums), never left to the model.
5. Test like the graders: records right AND conversation followed the brief. Read every failing conversation; fix the cause in the builder, never in one agent.
6. Generalisation check: develop on brief A, run cold on brief B. A gap means something is tuned to A.
7. Self-test inside the builder: invent test customers from the brief, run Freya text simulation, fix, finish. Keep it short (build time is the tie-break).
8. Nothing from a hidden brief may enter the builder.

## The 3-hour window (Sun 22:30 - Mon 01:30 IST)
22:15 laptop on charge, lid open, keep-awake, Claude + Freya logged in, final dry run done earlier
22:30 download hidden briefs into kit/hidden/
22:35 run builder once per brief (in parallel), keep the full trace
then: check each agent was created on Freya and runs (one text simulation each)
crash or odd table -> fix the parser bug only (no brief content in code), rerun that brief
~00:30 target: submit agents + code + traces; 01:30 hard close
