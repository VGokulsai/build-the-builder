"""Talk to a published workflow turn by turn (no simulation queue), then show the bank's ledger.

    py -3 kitlib/chat.py <workflow_id> PUB-01 "Yes, speaking." "14 March 1988" "4471" ...
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import freya  # noqa: E402
from score import http  # noqa: E402


def chat(workflow_id, case_id, lines, show=print):
    v = http("/v1/practice/sessions", {"case": case_id})["variables"]
    call_id, said = None, []
    for line in ["Hello?"] + list(lines):
        body = {"workflowId": workflow_id, "message": line, "customerVariables": v}
        if call_id:
            body["callId"] = call_id
        r = freya.api("POST", "/api/v2/chat/message", body)
        call_id = r.get("callId") or call_id
        show("CUSTOMER: " + line)
        show("AGENT:    " + str(r.get("response")))
        said.append(r.get("response"))
    try:
        freya.api("POST", "/api/v2/chat/end", {"callId": call_id})
    except Exception:
        pass
    led = http("/v1/practice/ledger/" + v["customer_id"])
    show("LEDGER: " + json.dumps({k: led.get(k) for k in ("outcome", "reason", "promises", "notes", "callbacks", "transfers")}))
    show("TOOLS:  " + " > ".join(c["tool"] for c in led.get("calls", [])))
    show("CALL:   " + str(call_id))
    return call_id, led


if __name__ == "__main__":
    chat(sys.argv[1], sys.argv[2], sys.argv[3:])
