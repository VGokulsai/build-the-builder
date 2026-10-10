"""The one door to a language model. Everything else calls ask().

Pick a backend with LLM_PROVIDER:
  anthropic  Claude, key in ANTHROPIC_API_KEY, model in LLM_MODEL
  openai     any OpenAI-compatible endpoint: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
  stub       canned answers, no network; for testing the loop itself
LLM_MODEL_<STEP> (e.g. LLM_MODEL_JUDGE, LLM_MODEL_REVISE) overrides LLM_MODEL for one step, so a
strong model can write and judge while a fast one plays the caller and the backend.
Standard library only, so a reproducible run needs no installs.
"""
import json
import os
import subprocess
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


class Blocked(RuntimeError):
    """The model cannot be reached in a way retrying will not fix (logged out, usage limit).
    Not retried, so the build falls back in seconds instead of waiting out every call."""


CALL_BUDGET = float(os.environ.get("CALL_BUDGET", "180"))   # seconds one call may take, retries included
DEADLINE = {"at": None}     # monotonic time when the whole build must stop calling the model
SLEEP, NOW = time.sleep, time.monotonic                      # tests swap these out


CALL_LOG = os.environ.get("CALL_LOG")    # a JSONL path: one line per model call, for diagnosing slow runs


LONG_REPLY = 3000          # max_tokens at or above this means a long structured answer (rules, judge, revise...)


def _attempt_cap(long_reply):
    """Longest one attempt may wait. Logged on 10 Oct: a short spoken line takes ~10 s, but a long
    structured answer (inventing customers, judging, rewriting the agent) took 40 s to over 60 s,
    so a single 60 s cap killed exactly those, again and again."""
    if long_reply:
        return float(os.environ.get("ATTEMPT_TIMEOUT_LONG", "240"))
    default = "60" if os.environ.get("LLM_PROVIDER") == "claude-cli" else "120"
    return float(os.environ.get("ATTEMPT_TIMEOUT", default))


def ask(role, prompt, system="", max_tokens=1500, tries=7):
    """Send one prompt; return the model's text. Retries rate limits, server errors
    and timeouts with backoff, because nobody can touch the builder during judging.
    A 429 waits as long as the server's Retry-After asks, else backs off up to a minute.
    No call outlives CALL_BUDGET or the build's DEADLINE, so a hung provider cannot
    freeze the builder past the hackathon deadline. With CALL_LOG set, every call is logged."""
    start, outcome = NOW(), "error"
    try:
        text = _ask_with_retries(role, prompt, system, max_tokens, tries, start)
        outcome = "ok"
        return text
    except Exception as e:
        outcome = type(e).__name__
        raise
    finally:
        if CALL_LOG:
            with _lock, open(CALL_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": round(time.time(), 1), "role": role, "secs": round(NOW() - start, 1),
                                    "outcome": outcome, "prompt_chars": len(prompt) + len(system)}) + "\n")


def _ask_with_retries(role, prompt, system, max_tokens, tries, start):
    long_reply = max_tokens >= LONG_REPLY
    cap = _attempt_cap(long_reply)
    budget = max(CALL_BUDGET, 2 * cap + 60) if long_reply else CALL_BUDGET   # room for one retry of a long answer
    for attempt in range(tries):
        left = min(budget - (NOW() - start),
                   DEADLINE["at"] - NOW() if DEADLINE["at"] is not None else budget)
        if left <= 1:
            raise OutOfTime("no time left for step %r" % role)
        wait = min(60, 2 * 2 ** attempt)
        try:
            return _ask(role, prompt, system, max_tokens, timeout=max(5.0, min(cap, left)))
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
        if NOW() - start + wait >= budget or (DEADLINE["at"] is not None and NOW() + wait >= DEADLINE["at"]):
            raise error         # waiting longer would break the budget: give up on this call now
        SLEEP(wait)


def model_for(role, default=None):
    """The model for one step: LLM_MODEL_<ROLE> if set, else LLM_MODEL, else the backend's default."""
    return os.environ.get("LLM_MODEL_" + role.upper()) or os.environ.get("LLM_MODEL") or default


def _ask(role, prompt, system, max_tokens, timeout=120.0):
    with _lock:
        CALLS["n"] += 1
    provider = os.environ.get("LLM_PROVIDER", "stub")
    if provider == "stub":
        from builder.stub import answer
        return answer(role, prompt, system)
    if provider == "anthropic":
        body = {"model": model_for(role, "claude-sonnet-5-5"), "max_tokens": max_tokens,
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
        body = {"model": model_for(role) or os.environ["LLM_MODEL"], "max_tokens": max_tokens, "messages": msgs}
        data = _post(os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions", body,
                     {"Authorization": "Bearer " + os.environ["LLM_API_KEY"]}, timeout)
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        if isinstance(text, list):          # content given as parts: [{"type": "text", "text": ...}]
            text = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in text)
        if choice.get("finish_reason") == "length":
            raise Truncated(text)
        return text
    if provider == "claude-cli":
        return _claude_cli(prompt, system, timeout, model_for(role, "claude-haiku-4-5-20251001"))
    raise SystemExit("Unknown LLM_PROVIDER: %r" % provider)


def _claude_cli(prompt, system, timeout, model="claude-haiku-4-5-20251001"):
    """The local `claude` login, headless. The flags strip CLAUDE.md, skills, plugins, tools and
    MCP servers out of each call (measured 14x cheaper on this machine, see cloud-pet/ask.py).
    The prompt goes on stdin: Windows caps a command line at 32 KB."""
    short = "Follow the user's instructions exactly."
    if len(system) > 4000:              # a long agent prompt would break the 32 KB command line: send it on stdin
        prompt = "SYSTEM INSTRUCTIONS (follow them exactly):\n%s\n\n---\n\n%s" % (system, prompt)
        system = short
    cmd = ["claude", "-p", "--model", model,
           "--output-format", "json", "--setting-sources", "", "--tools", "", "--strict-mcp-config",
           "--system-prompt", system or short]
    stdout, stderr = run_bounded(cmd, prompt, timeout)
    try:
        envelope = json.loads(stdout)
    except ValueError:
        raise ConnectionError("claude returned no JSON envelope: %s" % (stderr or stdout)[:200])
    if envelope.get("is_error"):       # no auth, usage limit, bad flag: the question never reached a model
        raise Blocked("claude error: %s" % str(envelope.get("result"))[:200])
    return envelope.get("result") or ""


def run_bounded(cmd, stdin_text, timeout):
    """Run a program and return (stdout, stderr), or raise TimeoutError close to `timeout`.
    subprocess.run's timeout is not enough on Windows: after killing the program it waits for
    any child process still holding the output pipes (reproduced: a 3 s timeout took 60 s).
    So on timeout the whole process tree is killed, and the pipes are never waited on for long."""
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        return p.communicate(stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        else:
            p.kill()
        try:
            p.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            for pipe in (p.stdin, p.stdout, p.stderr):
                try:
                    pipe and pipe.close()
                except OSError:
                    pass
        raise TimeoutError("%s did not answer in %.0fs" % (os.path.basename(cmd[0]), timeout))


def _post(url, body, headers, timeout=120.0):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    try:
        return json.loads(raw)
    except ValueError:                  # a gateway answered 200 with an HTML or empty body: transient, retry
        raise ConnectionError("non-JSON response from %s: %r" % (url, raw[:120]))


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
