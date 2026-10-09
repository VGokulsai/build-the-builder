# build-the-builder

An agent that builds agents, for YC x Freya's Build the Builder hackathon (10-11 Oct 2026).

Given a task description and its tools, it:

1. drafts an agent (instructions, tool rules, guardrails, opening line),
2. invents test customers for the task,
3. simulates a conversation with each one, with a model playing the customer and the system's tools,
4. has a judge score every conversation and list what went wrong,
5. revises the agent to fix those failures, for a few rounds, keeping the best version seen,
6. re-tests the winner on new customers it never trained on, and reports that score.

## Run it

Python 3.10+, standard library only.

```bash
LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=... python run.py tasks/bank_card_freeze.json --rounds 3 --scenarios 4
```

Output goes to `out/<task id>/agent.json` (the agent) and `out/<task id>/report.json` (every round's score and failures, the held-out score, model calls used).

Model backends (`LLM_PROVIDER`): `anthropic`, `openai` (any OpenAI-compatible endpoint: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`), or `stub` (canned answers, no network).

## Test

```bash
python test_builder.py
```

Runs the whole loop on the stub model, which is rigged so the second revision scores worse than the first. It checks that the builder keeps the best agent rather than the latest.

## Layout

- `builder/core.py`: the loop (draft, scenarios, simulate, judge, revise, build)
- `builder/llm.py`: the one door to a model
- `builder/platform.py`: the only Freya-specific code, turning an agent into their platform's format
- `builder/stub.py`: canned answers for tests
- `run.py`: the command above
