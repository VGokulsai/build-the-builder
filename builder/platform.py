"""The only Freya-specific code. Filled in at kickoff, once their platform docs are out.

Until then export() writes our own spec plus the full prompt the agent runs with,
so the rest of the builder can be built and tested without the platform.
"""
from builder.core import agent_prompt


def export(spec, task):
    """Our agent spec -> whatever Freya's platform takes for one agent."""
    # ponytail: our own format until the platform format is known (10 Oct kickoff)
    return {"task_id": task.get("id"), "prompt": agent_prompt(spec, task), **spec}
