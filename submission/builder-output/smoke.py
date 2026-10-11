"""Smoke chat with the saved final agent using the case's own call variables."""
import pathlib, sys, time
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import freya  # noqa: E402

wid, cust = sys.argv[1], sys.argv[2]
v = {"customerNumber": cust, "now": "2026-10-12T10:30:00+03:00"}
call_id = None
for line in ["Alo?"] + sys.argv[3:]:
    body = {"workflowId": wid, "message": line, "customerVariables": v}
    if call_id:
        body["callId"] = call_id
    r = freya.api("POST", "/api/v2/chat/message", body)
    call_id = r.get("callId") or call_id
    print("CUSTOMER:", line)
    print("AGENT:   ", r.get("response"))
try:
    freya.api("POST", "/api/v2/chat/end", {"callId": call_id})
except Exception:
    pass
