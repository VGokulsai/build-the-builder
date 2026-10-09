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


class OutOfTime(RuntimeError):
    """The whole build's time budget is spent; stop calling the model."""


CALL_BUDGET = float(os.environ.get("CALL_BUDGET", "180"))   # seconds one call may take, retries included
DEADLINE = {"at": None}     # monotonic time when the whole build must stop calling the model
SLEEP, NOW = time.sleep, time.monotonic                      # tests swap these out


def ask(role, prompt, system="", max_tokens=1500, tries=7):
    """Send one prompt; return the model's text. Retries rate limits, server errors
    and timeouts with backoff, because nobody can touch the builder during judging.
    A 429 waits as long as the server's Retry-After asks, else backs off up to a minute.
    No call outlives CALL_BUDGET or the build's DEADLINE, so a hung provider cannot
    freeze the builder past the hackathon deadline."""
    start = NOW()
    for attempt in range(tries):
        left = min(CALL_BUDGET - (NOW() - start),
                   DEADLINE["at"] - NOW() if DEADLINE["at"] is not None else CALL_BUDGET)
        if left <= 1:
            raise OutOfTime("no time left for step %r" % role)
        wait = min(60, 2 * 2 ** attempt)
        try:
            return _ask(role, prompt, system, max_tokens, timeout=max(5.0, min(120.0, left)))
        except urllib.error.HTTPError as e:
            if e.code not in (408, 409, 429, 500, 502, 503, 504, 529) or attempt == tries - 1:
                raise
            after = e.headers.get("Retry-After") if e.headers else None
            if after and after.strip().isdigit():
                wait = min(120, int(after.strip()) + 1)
            elif e.code == 429:
                wait = min(60, 5 * 2 ** attempt)
            error = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries - 1:
                raise
            error = e
        if NOW() - start + wait >= CALL_BUDGET or (DEADLINE["at"] is not None and NOW() + wait >= DEADLINE["at"]):
            raise error         # waiting longer would break the budget: give up on this call now
        SLEEP(wait)


def _ask(role, prompt, system, max_tokens, timeout=120.0):
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
                     {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}, timeout)
        text = "".join(b.get("text", "") for b in data["content"])
        if data.get("stop_reason") == "max_tokens":
            raise Truncated(text)
        return text
    if provider == "openai":
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = {"model": os.environ["LLM_MODEL"], "max_tokens": max_tokens, "messages": msgs}
        data = _post(os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions", body,
                     {"Authorization": "Bearer " + os.environ["LLM_API_KEY"]}, timeout)
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        if isinstance(text, list):          # content given as parts: [{"type": "text", "text": ...}]
            text = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in text)
        if choice.get("finish_reason") == "length":
            raise Truncated(text)
        return text
    raise SystemExit("Unknown LLM_PROVIDER: %r" % provider)


def _post(url, body, headers, timeout=120.0):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
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
