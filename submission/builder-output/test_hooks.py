"""Run the final agent's hooks locally against the mock, the way the platform runs them."""
import json, pathlib, sys, urllib.request, urllib.error
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "out" / "final"))
import agent

W = agent.build()
TOOLS = {t["function"]["name"]: t for t in W["nodes"]["main"]["tools"] + W["nodes"]["fetch_cards"]["pre_actions"] + W["nodes"]["fetch_email"]["pre_actions"]}


def call(v, name, **model):
    t = TOOLS[name]
    props = t["function"]["parameters"]["properties"]
    body = {}
    for f, leaf in props["body"]["properties"].items():
        val = model.get(f, leaf["default"])
        if isinstance(val, str) and val.startswith("{{"):
            val = v.get(val[2:-2], "")
        if isinstance(val, dict):
            val = {a: (v.get(x[2:-2], "") if isinstance(x, str) and x.startswith("{{") else x) for a, x in val.items()}
        body[f] = val
    config = {"url": props["url"]["default"], "body": body}
    exec(t["pre_process_code"], {"config": config, "vars": v})
    req = urllib.request.Request(config["url"], data=json.dumps(config["body"]).encode(), headers={"Content-Type": "application/json", "User-Agent": "curl/8"}, method="POST")
    try:
        res = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        return "HTTP %s" % e.code
    exec(t["post_process_code"], {"result": res, "vars": v})
    return res.get("data")


def setup(cust, now="2026-10-12T10:30:00+03:00"):
    v = {"customerNumber": cust, "now": now}
    code = W["nodes"]["setup"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    exec(code, {"vars": v})
    return v


# Example 1: one card, paid below minimum, Euro debt, USD+GBP clear.
v = setup("95004361")
r = call(v, "cards_list"); print(r)
b = call(v, "cards_balance", cardNumber="K1"); print(b)
s = b["reading"]
assert "Sonu iki sıfır sıfır sıfır ile biten Yıldız Premium" in s and "5 Ekim 2026" in s
assert "on iki bin Türk Lirası" in s and "kalan minimum ödeme tutarınız iki bin Türk Lirası'dır" in s
assert "seksen beş euro yirmi sent" in s and "Dolar ve İngiliz Sterlini borcunuz bulunmamaktadır." in s
assert "15 Ekim 2026'dır" in s
print(call(v, "contact_email_get"))
# Example 2: week change.
v = setup("96158684")
call(v, "cards_list"); print(call(v, "cards_balance", cardNumber="K1")["reading"])
print(call(v, "statement_week_get", cardNumber="K1"))
blocked = call(v, "statement_week_change", cardNumber="K1", newStatementWeek="3"); print(blocked)
assert blocked.get("ok") is False
p = call(v, "statement_week_decide", cardNumber="K1", newStatementWeek="3"); print(p)
assert "16 Kasım 2026" in p["say_now"] and "26 Kasım 2026" in p["say_now"]
# Example 6: no email.
v = setup("96125950")
call(v, "cards_list"); print(call(v, "cards_balance", cardNumber="K1")["reading"])
e = call(v, "contact_email_get"); print(e)
assert e["offer"] == "Hesap kesim tarihinizi değiştirebilirim."
x = call(v, "statement_pdf_send", cardNumber="K1"); print(x)
assert x["sent"] is False
# New card without a statement, multi-card, errors.
v = setup("97631186"); call(v, "cards_list"); print(call(v, "cards_balance", cardNumber="K1"))
v = setup("97526380"); print(call(v, "cards_list"))
v = setup("93821776"); print(call(v, "cards_list"))
v = setup("92460108"); call(v, "cards_list"); print(call(v, "cards_balance", cardNumber="K1")["reading"])
print("ALL OK")
