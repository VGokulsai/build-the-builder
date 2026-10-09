"""The one door to a language model. Everything else calls ask().

Pick a backend with LLM_PROVIDER:
  anthropic  Claude, key in ANTHROPIC_API_KEY, model in LLM_MODEL
  openai     any OpenAI-compatible endpoint: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
  stub       canned answers, no network; for testing the loop itself
Standard library only, so a reproducible run needs no installs.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request

CALLS = {"n": 0}          # how many model calls this run made (for budgets and logs)
_lock = threading.Lock()  # calls run in parallel threads


class Truncated(ValueError):
    """The model hit its length limit, so the reply is incomplete and must not be parsed."""


def ask(role, prompt, system="", max_tokens=1500, tries=4):
    """Send one prompt; return the model's text. Retries rate limits, server errors
    and timeouts with backoff, because nobody can touch the builder during judging."""
    for attempt in range(tries):
        try:
            return _ask(role, prompt, system, max_tokens)
        except urllib.error.HTTPError as e:
            if e.code not in (408, 409, 429, 500, 502, 503, 504, 529) or attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == tries - 1:
                raise
        time.sleep(2 ** attempt * 2)


def _ask(role, prompt, system, max_tokens):
    with _lock:
        CALLS["n"] += 1
    provider = os.environ.get("LLM_PROVIDER", "stub")
    if provider == "stub":
        from builder.stub import answer
        return answer(role, prompt, system)
    if provider == "anthropic":
        body = {"model": os.environ.get("LLM_MODEL", "claude-sonnet-5-5"), "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system
        data = _post("https://api.anthropic.com/v1/messages", body,
                     {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
        text = "".join(b.get("text", "") for b in data["content"])
        if data.get("stop_reason") == "max_tokens":
            raise Truncated(text)
        return text
    if provider == "openai":
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = {"model": os.environ["LLM_MODEL"], "max_tokens": max_tokens, "messages": msgs}
        data = _post(os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions", body,
                     {"Authorization": "Bearer " + os.environ["LLM_API_KEY"]})
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        if choice.get("finish_reason") == "length":
            raise Truncated(text)
        return text
    raise SystemExit("Unknown LLM_PROVIDER: %r" % provider)


def _post(url, body, headers):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def ask_json(role, prompt, system="", max_tokens=4000):
    """ask(), then parse the reply's JSON. Only JSON that runs to the end of the reply counts,
    so a fragment inside a cut-off answer is never mistaken for the answer. A reply that hit the
    length limit is retried with twice the room; bad JSON is retried once."""
    text = ""
    for attempt in range(3):
        try:
            text = ask(role, prompt + ("" if attempt == 0 else "\n\nReply with valid JSON only."), system, max_tokens)
        except Truncated:
            max_tokens = min(max_tokens * 2, 16000)
            continue
        value = parse_json(text)
        if value is not None:
            return value
    raise ValueError("model gave no complete JSON for step %r: %r" % (role, text[:200]))


def parse_json(text):
    """The JSON value that ends the reply (code fences and trailing punctuation allowed), or None."""
    body = text.strip()
    if body.endswith("```"):
        body = body[:-3].rstrip()
    for i, ch in enumerate(body):
        if ch in "{[":
            try:
                value, end = json.JSONDecoder().raw_decode(body[i:])
            except json.JSONDecodeError:
                continue
            if not body[i + end:].strip(" \n\t.`"):
                return value
    return None
