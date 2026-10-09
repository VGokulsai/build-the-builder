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
                "system": system, "messages": [{"role": "user", "content": prompt}]}
        data = _post("https://api.anthropic.com/v1/messages", body,
                     {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
        return "".join(b.get("text", "") for b in data["content"])
    if provider == "openai":
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = {"model": os.environ["LLM_MODEL"], "max_tokens": max_tokens, "messages": msgs}
        data = _post(os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions", body,
                     {"Authorization": "Bearer " + os.environ["LLM_API_KEY"]})
        return data["choices"][0]["message"]["content"]
    raise SystemExit("Unknown LLM_PROVIDER: %r" % provider)


def _post(url, body, headers):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def ask_json(role, prompt, system=""):
    """ask(), then parse the first JSON object or array in the reply. Retries once on bad JSON."""
    for attempt in range(2):
        text = ask(role, prompt + ("" if attempt == 0 else "\n\nReply with valid JSON only."), system)
        start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
        if start >= 0:
            try:
                return json.JSONDecoder().raw_decode(text[start:])[0]
            except json.JSONDecodeError:
                pass
    raise ValueError("model gave no valid JSON for step %r: %r" % (role, text[:200]))
