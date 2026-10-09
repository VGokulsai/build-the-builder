"""The only Freya-specific code. Filled in at kickoff, once their platform docs are out.

Until then export() writes our own spec format, so the rest of the builder can
be built and tested without the platform.
"""


def export(spec, task):
    """Our agent spec -> whatever Freya's platform takes for one agent."""
    # ponytail: identity until the platform format is known (10 Oct kickoff)
    return {"task_id": task.get("id"), **spec}
