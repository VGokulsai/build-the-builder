# Final window runbook (Sun 11 Oct, 17:00-20:00 UTC = 22:30-01:30 IST)

Rules that bind us in the window: run the builder once per final brief with no manual step; we may fix
a crash or parser bug in the builder, never add anything from a final brief (no rule, value or name) to
the builder's code, skill or prompts; submit the phone agents (exported files), our code and the
builder's trace for each brief. A builder run may take 30 minutes at most.

## Before 22:30
- Laptop on charge, lid open. Claude Code logged in (`claude` works), Freya signed in.
- `cd build-the-builder/kit/build-the-builder && source env.sh`
- Check the kit version: if a newer kit was mailed, read its README changes first.
- Workspace slots: final agents go to slots named after the final brief files, never reusing practice slots.

## At 22:30
1. Download the final briefs and their tool API files into `final/` (one folder each if names clash).
2. For each brief, in parallel terminals:
   `python3 build.py final/<brief>.md --api final/<api>.json`
   (if a final brief builds on another, pass both, the base first.)
   No `--practice`: the final briefs have no practice customers.
3. Read each run's final line and `traces/<slot>-*.txt`. Check: lint clean, local tests pass, agent saved,
   export written to `out/<slot>.workflow.json`.
4. If a run crashed: read the error, fix the builder's code only if it is a generic bug, then rerun that
   brief from scratch. Never hand-edit an agent.

## Submit (target 00:30, hard close 01:30)
- `out/<slot>.workflow.json` for each final brief (made by `freya.export_workflow`).
- The trace pair for the submitted run: `traces/<slot>-<time>.txt` and `.jsonl`.
- Our code: build.py, kitlib/, agents/ref_ab.py, tests/, .claude/skills/collections-builder/, briefs-test/.
- Follow the organisers' submission steps (they mail them before 17:00 UTC).
