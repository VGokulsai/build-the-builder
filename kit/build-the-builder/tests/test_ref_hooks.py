"""Run the reference workflow's hooks and code nodes locally, the way the platform runs them."""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "agents"))
import ref_ab

def tool(w, node, name):
    return next(t for t in w["nodes"][node].get("tools", []) + w["nodes"][node].get("pre_actions", []) if t["function"]["name"] == name)

def post(t, data, vars_):
    result = {"status": "success", "data": data, "header": {"x": "y"}}
    exec(t["post_process_code"], {"result": result, "vars": vars_})
    return result

def pre(t, body, vars_):
    config = {"url": "https://x/v1/" + t["function"]["name"], "body": dict(body)}
    exec(t["pre_process_code"], {"config": config, "vars": vars_})
    return config

for brief in ("A", "B"):
    w = ref_ab.build(brief)
    v = {"now": "2026-10-14T11:00", "customer_id": "c1"}
    code = w["nodes"]["setup"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    exec(code, {"vars": v})
    assert v["setup_state"] == "ok", v["setup_state"]
    assert "Friday 16 October 2026 (2026-10-16)" in v["date_facts"] and "HOLIDAY" in v["date_facts"]
    assert "Thursday 15 October 2026 (2026-10-15) from 10:00 to 19:00" in v["callback_window"], v["callback_window"]
    r = post(tool(w, "fetch_account", "get_account"), {"ok": True, "products": [
        {"product_id": "p1", "type": "credit_card", "card_last4": "4821", "past_due": 300, "days_late": 4, "minimum_payment": 90},
        {"product_id": "p2", "type": "personal_loan", "past_due": 900, "days_late": 20, "instalment_amount": 300}]}, v)
    assert v["account_state"] == "loaded" and "header" not in r and r["data"]["what_to_do_next"], v
    assert "2026-11-02" in v["account_facts"] and "2026-10-23" in v["account_facts"], v["account_facts"]
    assert "credit card ending 4821" in v["account_facts"]
    vd = {"now": "2026-10-14T11:00"}; post(tool(w, "fetch_account", "get_account"), {"ok": True, "products": [{"product_id": "p1", "type": "car_loan", "past_due": 5, "days_late": 9, "instalment_amount": 2}]}, vd)
    assert "Today is 2026-10-14" in vd["date_facts"], vd.get("date_facts")  # works even when setup was skipped
    cp = tool(w, "negotiate", "create_promise")
    cases = [({"product_id": "p1", "amount": 300, "date": "2026-10-30"}, ""),           # inside early deadline
             ({"product_id": "p2", "amount": 900, "date": "2026-10-30"}, "deadline"),   # PUB-13: loan after its deadline
             ({"product_id": "p1", "amount": 300, "date": "2026-10-26"}, "business day"),  # holiday
             ({"product_id": "p1", "amount": 50, "date": "2026-10-16"}, "floor"),
             ({"product_id": "p9", "amount": 50, "date": "2026-10-16"}, "does not exist"),
             ({"product_id": "p1", "amount": 300, "date": "2026-10-13"}, "past")]
    for body, want in cases:
        c = pre(cp, body, v)
        blocked = c["url"].endswith("/get_account")
        assert not blocked or c["body"] == {"customer_id": None} or set(c["body"]) == {"customer_id"}, c["body"]
        assert blocked == bool(want) and want in v["promise_block"], (body, v["promise_block"], c["url"])
    v["create_promise_args.product_id"] = "p1"; pre(cp, cases[0][0], v)
    r = post(cp, {"ok": True, "promise_id": "x"}, v)
    assert json.loads(v["promises_done"]) == ["p1"] and "text message" in r["data"]["what_to_do_next"]
    c = pre(cp, cases[0][0], v); assert c["url"].endswith("/get_account") and "already recorded" in v["promise_block"]
    # service failure: first retry, then give up
    v2 = dict(v, promises_done="[]", promise_block=""); v2["create_promise_args.product_id"] = "p2"
    r = post(cp, {"ok": False, "error": "service unavailable"}, v2); assert "again" in r["data"]["what_to_do_next"]
    r = post(cp, {"ok": False, "error": "service unavailable"}, v2); assert "failed twice" in r["data"]["what_to_do_next"]
    # blocked promise reads as not recorded
    v3 = dict(v, promise_block="the date is in the past."); r = post(cp, {"ok": True, "products": [{"product_id": "p1"}]}, v3)
    assert "products" not in r["data"] and r["data"]["ok"] is False, r["data"]
    assert r["data"]["what_to_do_next"].startswith("NOT recorded")
    # close_call guard: a recorded promise wins, a transfer wins over it, reason dropped for promise
    cc = tool(w, "negotiate", "close_call")
    assert pre(cc, {"outcome": "no_promise", "reason": "refused"}, dict(v, promises_done='["p1"]'))["body"] == {"outcome": "promise"}
    assert pre(cc, {"outcome": "promise"}, dict(v, promises_done='["p1"]', transfer_queue="restructuring"))["body"] == {"outcome": "transferred", "reason": "restructuring"}
    assert pre(cc, {"outcome": "transferred", "reason": "x"}, dict(v, promises_done="[]", transfer_queue="general"))["body"]["reason"] == "human"
    if brief == "B":
        an = tool(w, "negotiate", "add_note")
        vb = dict(v, promises_done="[]", notes_done="[]")
        for pid, why in (("p1", "paid"), ("p2", "dispute")):
            vb["add_note_args.product_id"], vb["add_note_args.reason"] = pid, why
            post(an, {"ok": True}, vb)
        assert pre(cc, {"outcome": "paid"}, vb)["body"] == {"outcome": "no_promise", "reason": "dispute"}
        vb["notes_done"] = '[["p1","paid"],["p2","paid"]]'
        assert pre(cc, {"outcome": "no_promise", "reason": "refused"}, vb)["body"] == {"outcome": "paid"}
    vh = tool(w, "identity", "verify_identity")
    assert "month" in post(vh, {"ok": False, "hint": "day_month_swapped"}, {})["data"]["what_to_do_next"]
    assert "last four" in post(vh, {"ok": True, "verified": True, "wrong_answers_left": 3, "all_verified": False}, {})["data"]["what_to_do_next"]
    assert "2 wrong" in post(vh, {"ok": True, "verified": False, "wrong_answers_left": 2}, {})["data"]["what_to_do_next"]
    assert "ended" in post(vh, {"ok": True, "verified": False, "wrong_answers_left": 0}, {})["data"]["what_to_do_next"]
    print("brief", brief, "hooks ok")
