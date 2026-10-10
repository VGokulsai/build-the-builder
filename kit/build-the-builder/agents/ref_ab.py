"""Hand-written reference agent for Briefs A and B, built with kitlib.

Not the builder: this is where we learn what the platform and its model need, so the
builder's skill can teach it. Usage:
    py -3 agents/ref_ab.py A        # writes out/ref-a.workflow.json and saves slot ref-a
    py -3 agents/ref_ab.py B
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from kitlib import wf, datekit  # noqa: E402

# BRIEF A section 7: business days are Monday to Friday except these holidays.
HOLIDAYS = ["2026-10-26", "2026-11-11", "2026-11-26", "2026-12-25", "2027-01-01"]
LIB = datekit.date_lib(HOLIDAYS)

# ----------------------------------------------------------------- code run inside the workflow

SETUP = LIB + '''
try:
    now = str(vars.get('now') or '')
    today = to_date(now)
    hhmm = now[11:16] if len(now) >= 16 else '00:00'
    nb = next_bd(today)
    # BRIEF A rule 30: attempt 1 = last business day of this week; if today is that day, of next week.
    a1 = last_bd_of_week(today)
    if a1 is None or a1 <= today:
        a1 = last_bd_of_week(today + datetime.timedelta(days=7))
    vars['today_iso'] = today.isoformat()
    vars['attempt1_date'] = a1.isoformat()
    # BRIEF A rule 6: callback today or the next business day, 10:00-19:00, later than now.
    cb_today = ('today ' + say(today) + ' from ' + max(hhmm, '10:00') + ' to 19:00') if hhmm < '19:00' else ''
    vars['callback_window'] = ((cb_today + ', or ') if cb_today else '') + say(nb) + ' from 10:00 to 19:00'
    lines = ['Now: ' + say(today) + ', time ' + hhmm + '.',
             'Calendar (use it for every date; never compute dates yourself):', day_table(today, 3)]
    vars['date_facts'] = chr(10).join(lines)
    vars['promises_done'] = '[]'
    vars['notes_done'] = '[]'
    vars['transfer_queue'] = ''
    vars['setup_state'] = 'ok'
except Exception as e:
    vars['date_facts'] = 'Date facts unavailable.'
    vars['callback_window'] = 'today or the next business day, from 10:00 to 19:00'
    vars['setup_state'] = 'error ' + str(e)
'''

# The product facts are computed in get_account's post-hook, where the products are in hand.
ACCOUNT_HOOK = LIB + '''
# BRIEF A rule 17: product names in words.
WORDS = dict(credit_card='credit card', personal_loan='personal loan', car_loan='car loan')
if d.get('ok') and isinstance(d.get('products'), list):
    today = to_date(vars.get('now'))
    a1 = last_bd_of_week(today)
    if a1 is None or a1 <= today:
        a1 = last_bd_of_week(today + datetime.timedelta(days=7))
    prods, lines = [], []
    for p in d['products']:
        late = int(p.get('days_late') or 0)
        # BRIEF A rule 18: bands by days_late, deadline = Nth business day after today; rule 25: floor field per type.
        band = 'early' if late <= 7 else 'late'
        deadline = add_bd(today, 12 if band == 'early' else 7)
        floor = p.get('minimum_payment') if p.get('type') == 'credit_card' else p.get('instalment_amount')
        name = WORDS.get(p.get('type'), str(p.get('type')).replace('_', ' '))
        if p.get('type') == 'credit_card' and p.get('card_last4'):
            name = name + ' ending ' + str(p.get('card_last4'))
        a1_date = a1 if a1 <= deadline else deadline
        prods.append(dict(id=p.get('product_id'), name=name, past_due=float(p.get('past_due') or 0),
                          floor=float(floor or 0), deadline=deadline.isoformat(), band=band,
                          attempts=1 if band == 'early' else 2, a1=a1_date.isoformat()))  # BRIEF A rule 18: attempts per band
        q = prods[-1]
        txt = (q['id'] + ': the ' + name + '. Past due ' + money(q['past_due']) + ' dollars, ' + str(late) + ' days late. '
               + band.capitalize() + ' band: latest allowed promise date (deadline) ' + say(deadline) + '. '
               + 'Lowest amount you may accept (floor): ' + money(q['floor']) + ' dollars. '
               + 'Persuasion attempts allowed: ' + str(q['attempts']) + '. '
               + 'Attempt 1: propose ' + money(q['past_due']) + ' dollars (or the floor ' + money(q['floor'])
               + ' if the customer already said the full amount is too much) on ' + say(a1_date) + '.')
        if q['attempts'] == 2:
            txt = txt + ' Attempt 2: propose the floor ' + money(q['floor']) + ' dollars on the deadline ' + say(deadline) + '.'
        lines.append(txt)
    vars['products_json'] = json.dumps(prods)
    vars['product_count'] = str(len(prods))
    vars['account_facts'] = chr(10).join(lines)
    hhmm = str(vars.get('now') or '')[11:16]
    vars['date_facts'] = chr(10).join(['Now: ' + say(today) + ', time ' + hhmm + '. Today is ' + today.isoformat() + '.',
                                      'Calendar (use it for every date; never compute dates yourself):', day_table(today, 3)])
    vars['account_state'] = 'loaded'
    nxt = 'Account loaded. Now state the debt as your task says.'
else:
    vars['account_state'] = 'failed'
    nxt = 'The account could not be loaded. Tell the customer you cannot see the account details right now.'
'''

# BRIEF A rules 19, 20, 23, 27, 36 are checked here; replace them with the new brief's date and amount rules.
# Guard: a promise the brief does not allow never reaches the bank. The request is sent to a
# path that does not exist instead, and the post-hook tells the agent what to offer.
PROMISE_GUARD = LIB + '''
vars['promise_block'] = ''
b = config.get('body') or dict()
prods = json.loads(vars.get('products_json') or '[]')
done = json.loads(vars.get('promises_done') or '[]')
p = [x for x in prods if x['id'] == str(b.get('product_id'))]
why = ''
if not p:
    why = 'product_id ' + str(b.get('product_id')) + ' does not exist. Use one of: ' + ', '.join(x['id'] for x in prods) + '.'
else:
    p = p[0]
    today = to_date(vars.get('now'))
    try:
        day = to_date(b.get('date'))
    except Exception:
        day = None
    amt = float(b.get('amount') or 0)
    if p['id'] in done:
        why = 'a promise for this product is already recorded; it cannot be changed in this call (the customer can use the mobile app).'
    elif day is None:
        why = 'the date is not a valid YYYY-MM-DD date.'
    elif day < today:
        why = 'the date is in the past. Offer a date from today.'
    elif day > to_date(p['deadline']):
        why = 'the date is after the deadline. The latest date you can record is ' + say(to_date(p['deadline'])) + '. Offer it.'
    elif not is_bd(day):
        why = say(day) + ' is not a business day. Offer the next business day, ' + say(bd_on_or_after(day)) + '.'
    elif amt > p['past_due'] + 0.001:
        why = 'the amount is above the past-due amount ' + money(p['past_due']) + '.'
    elif amt < p['floor'] - 0.001:
        why = 'the amount is below the floor. Say it cannot be recorded and offer the floor ' + money(p['floor']) + ' dollars once.'
if why:
    vars['promise_block'] = why
    config['url'] = str(config.get('url')) + '_blocked_by_rules'
'''

PROMISE_HOOK = '''
blk = vars.get('promise_block') or ''
pid = str(vars.get('create_promise_args.product_id') or '')
if blk:
    d['ok'] = False
    d['error'] = 'not allowed by the bank rules'
    nxt = 'NOT recorded, nothing was sent to the bank: ' + blk + ' Never say it is recorded.'
elif d.get('ok'):
    done = json.loads(vars.get('promises_done') or '[]')
    done.append(pid)
    vars['promises_done'] = json.dumps(done)
    nxt = 'Recorded. Tell the customer the promise is recorded and say exactly: You will receive a text message confirming this promise.'
else:
    fails = json.loads(vars.get('promise_fails') or '[]')
    fails.append(pid)
    vars['promise_fails'] = json.dumps(fails)
    if fails.count(pid) < 2:
        nxt = 'The bank did not record it. Do not tell the customer it is recorded. CALL create_promise again now, once, with the same values.'
    else:
        nxt = 'It failed twice. Tell the customer you could not record this promise.%s'
'''

TRANSFER_HOOK = '''
if d.get('ok'):
    vars['transfer_queue'] = str(vars.get('transfer_to_agent_args.queue') or '')
    nxt = 'Transferred. Say goodbye in one short sentence and CALL close_call now.'
else:
    nxt = 'The transfer did not go through. Tell the customer, then continue.'
'''

NOTE_HOOK = '''
if d.get('ok'):
    notes = json.loads(vars.get('notes_done') or '[]')
    notes.append([str(vars.get('add_note_args.product_id') or ''), str(vars.get('add_note_args.reason') or '')])
    vars['notes_done'] = json.dumps(notes)
    nxt = 'Note recorded. Continue with the next product, or close the call if every product is done.'
else:
    nxt = 'The note was not recorded. CALL add_note again once.'
'''

# close_call: the outcome follows from what was recorded, not from the model's memory.
CLOSE_GUARD_A = '''
import json
b = config.get('body') or dict()
q = vars.get('transfer_queue') or ''
done = json.loads(vars.get('promises_done') or '[]')
TQ = dict(restructuring='restructuring', general='human', support='support')  # BRIEF A table: transfer queue -> reason
if q:
    b['outcome'] = 'transferred'
    b['reason'] = TQ.get(q, q)
elif done:
    b['outcome'] = 'promise'
if b.get('outcome') in ('promise', 'paid'):
    b.pop('reason', None)
config['body'] = b
'''

# BRIEF B closing section: no promise -> paid if every note is paid, else no_promise with the first non-paid note's reason.
CLOSE_GUARD_B = '''
import json
b = config.get('body') or dict()
q = vars.get('transfer_queue') or ''
done = json.loads(vars.get('promises_done') or '[]')
notes = json.loads(vars.get('notes_done') or '[]')
prods = json.loads(vars.get('products_json') or '[]')
TQ = dict(restructuring='restructuring', general='human', support='support')
if q:
    b['outcome'] = 'transferred'
    b['reason'] = TQ.get(q, q)
elif done:
    b['outcome'] = 'promise'
elif notes and prods:
    by = dict((n[0], n[1]) for n in notes)
    reasons = [by.get(p['id']) for p in prods if by.get(p['id'])]
    if reasons and all(r == 'paid' for r in reasons):
        b['outcome'] = 'paid'
    else:
        first = [r for r in reasons if r != 'paid']
        if first:
            b['outcome'] = 'no_promise'
            b['reason'] = first[0]
if b.get('outcome') in ('promise', 'paid'):
    b.pop('reason', None)
config['body'] = b
'''

CLOSE_HOOK = '''
if d.get('ok'):
    nxt = 'The call is closed. Say nothing more.'
else:
    nxt = 'close_call failed. CALL close_call again once with the same values.'
'''

# BRIEF A rules 11-14: the questions, their order, the swapped-date hint and the wrong-answer limit.
VERIFY_HOOK = '''
left = d.get('wrong_answers_left')
if d.get('hint') == 'day_month_swapped':
    nxt = 'The day and month look swapped. Ask the customer to say the month of their date of birth as a word. This retry is not a wrong answer.'
elif not d.get('ok'):
    nxt = 'The answer could not be read (not counted as wrong). Ask for it again.'
elif str(d.get('all_verified')).lower() == 'true':
    nxt = 'Identity verified. Say only: Thank you.'
elif str(d.get('verified')).lower() == 'true':
    nxt = 'Correct. Now ask the next security question: the last four digits of the phone number on file.'
elif left is not None and int(left) <= 0:
    nxt = 'Three wrong answers: the check has ended. Do not state any debt.'
else:
    nxt = 'That answer is wrong (' + str(left) + ' wrong answers left in total). Ask the same question again once more. Do not reveal the right answer.'
'''

CALLBACK_HOOK = '''
if d.get('ok'):
    nxt = 'Callback booked. Thank the person, say goodbye, and CALL close_call with outcome not_reached and reason callback.'
else:
    nxt = 'The callback was not booked (' + str(d.get('error')) + '). Ask for another time inside the window.'
'''

# ----------------------------------------------------------------- prompts

# BRIEF: every prompt below restates the brief's rules. Rewrite them from the new brief; keep the shape.
SYSTEM = """You are the digital assistant of Freya Bank, on an outbound phone call. Speak English. One or two short sentences per turn, one question at a time.
Rules for the whole call:
- Never invent figures, dates or reasons. If you do not have the information, say you do not have that information.
- If asked whether you are a robot or an AI: say you are Freya Bank's digital assistant, then continue.
- If asked whether this is a scam: say they can verify the call by phoning Freya Bank's customer service number, then continue.
- Never offer a discount, a waiver, an instalment plan or any term the bank did not give you.
- After every tool result, either speak to the customer or call the next tool. Never end a turn with nothing.
- Call one tool per message. When a tool result has what_to_do_next, follow it.
- Before you call close_call, thank the customer and say goodbye in the same message. close_call is always the last tool call."""

OPENING = """Find out whether the person on the line is {{title}} {{first_name}} {{last_name}}. You have already said who you are and asked "Am I speaking with {{title}} {{last_name}}?".
- Only "yes", "that's me", "speaking" or the customer's own name confirms it. "Hello", "go ahead" and "who is this" do not: ask once more "Am I speaking with {{title}} {{last_name}}?". If a question comes first, answer it, then ask.
- Until identity is checked you must not say why you are calling: never say collections, debt, payment, amount or the product.
- If it is still unclear after the second ask, say goodbye and CALL close_call with outcome not_reached and reason unclear.
- If the person says the number is not the customer's: say goodbye and CALL close_call with outcome not_reached and reason wrong_number.
- If the person says the customer has died: say exactly "I am sorry for your loss.", say goodbye, ask nothing else, and CALL close_call with outcome not_reached and reason deceased.
- If the person says twice that they do not want to talk: say goodbye and CALL close_call with outcome not_verified and reason declined.
- If the person asks for a human: ask once whether you can help first. If they insist, CALL transfer_to_agent with queue general."""

THIRD_PARTY = """The person on the line is not the customer. Do not say why you are calling and say nothing about any account, debt, payment or product, even if they ask or offer to pay. Do not ask them security questions.
Ask when {{title}} {{last_name}} can be reached. A callback may be: {{callback_window}}. Times are HH:MM, 24 hour.
- When they give a day and a time inside that window, CALL schedule_callback with the date (YYYY-MM-DD) and the time (HH:MM).
- If they give a day or time outside the window, ask once for another time inside it. If that is also outside, do not schedule: say goodbye and CALL close_call with outcome not_reached and reason no_callback.
- If they say the number does not belong to the customer: goodbye, then CALL close_call with outcome not_reached and reason wrong_number.
- If they say the customer has died: say exactly "I am sorry for your loss.", ask nothing else, goodbye, and CALL close_call with outcome not_reached and reason deceased.
{{date_facts}}"""

IDENTITY = """The customer confirmed who they are. Check identity with two security questions, one at a time:
1. Ask for their date of birth. CALL verify_identity with field date_of_birth and the date as YYYY-MM-DD, whatever way they said it. A date said only in numbers is day, then month, then year.
2. After that passes, ask for the last four digits of the phone number on file. CALL verify_identity with field phone_last4 and the four digits.
CALL verify_identity every time the customer gives an answer. Never judge an answer yourself. Do not say why you are calling until identity is verified: never say collections, debt, payment, amount or the product.
- If the customer does not want to answer, or asks what the call is about instead of answering: explain once that the questions protect their account. If they refuse again or ask again, say goodbye and CALL close_call with outcome not_verified and reason declined.
- After three wrong answers in total: tell them to use the mobile app or visit a branch, say goodbye, and CALL close_call with outcome not_verified and reason failed. Do not state any debt.
- If they ask for a human: ask once whether you can help first. If they insist, CALL transfer_to_agent with queue general."""

NEGOTIATE_A = """Identity is verified. You are calling from the collections team about a late payment.
Account facts (exact; use only these numbers and dates):
{{account_facts}}

{{date_facts}}

How the call goes:
1. Say you are calling from the collections team about a late payment. Name the product in words, the past-due amount and how many days late it is. Then ask exactly: "Can you make this payment today?"
2. Always propose amounts yourself. First ask for the full past-due amount. Never ask how much they can pay.
3. A date or an amount the customer proposes is never a refusal. Check it against the facts: a promise date must be today or later, a business day, and not after the deadline. If they name a weekend day or a holiday not after the deadline, offer the next business day. If their date is after the deadline, say the latest date you can record is the deadline and offer it; if they refuse the deadline, that is a flat refusal. If they give a vague period (next week, end of the month, when my salary comes), ask once for the exact day; if they still give none, propose the deadline. "Next Friday" means Friday of the following calendar week, "this Friday" the one in the current week.
4. If they say the full amount is too much: make ONE offer that names the floor and the attempt 1 date together, for example: "I can accept the minimum payment of <floor> dollars; the rest stays overdue. Could you pay that on <attempt 1 date>?" That offer is attempt 1. Never name the floor again, except in attempt 2 (on the deadline). If they ask what the minimum is, say it is the amount you just offered. An amount from the floor up to the full amount is accepted. Below the floor: say it cannot be recorded and offer the floor once.
5. A flat refusal or a non-answer uses one persuasion attempt (the attempts are in the facts). When the attempts are used up, stop: do not repeat an offer they refused. Say goodbye and CALL close_call with outcome no_promise and reason refused.
6. When you have an amount and a date: read back the product, the amount and the date and ask "Do you confirm?". CALL create_promise only after a clear yes. If they change the date or the amount, check it again and read it back again.
7. After the promise is recorded, say "You will receive a text message confirming this promise.", thank them, say goodbye and CALL close_call with outcome promise.
Other situations:
- Illness, a death in the family or job loss: one short sentence of sympathy, no persuasion. Offer to connect them with the customer support team. If they accept, CALL transfer_to_agent with queue support. If they decline, say goodbye and CALL close_call with outcome no_promise and reason hardship. If they still name a date or amount themselves, record that promise.
- "I already paid": say payments can take one business day to appear, take no promise, say goodbye and CALL close_call with outcome paid.
- "This debt is not mine", "I never had this product", or the product was closed or paid off in the past: do not argue, take no promise, say goodbye and CALL close_call with outcome no_promise and reason dispute.
- A new payment plan or lower instalments: do not describe any plan. CALL transfer_to_agent with queue restructuring.
- A request for a human: ask once whether you can help first. If they insist, CALL transfer_to_agent with queue general.
- If they say twice they do not want to talk: say goodbye and CALL close_call with outcome no_promise and reason refused.
- A recorded promise cannot be changed or cancelled in this call; they can change it in the mobile app.
- If a promise could not be recorded after two tries: say you could not record it, say goodbye and CALL close_call with outcome no_promise and reason service_error."""

NEGOTIATE_B = """Identity is verified. You are calling from the collections team about late payments. The customer can have up to three late products.
Account facts (exact; use only these numbers and dates; products in this order):
{{account_facts}}

{{date_facts}}

How the call goes:
1. Say you are calling from the collections team about late payments. State every late product, one sentence each (product in words, past-due amount, days late), before asking anything. Then ask whether they can pay all of them today.
2. If not, go through the products one by one in the order above. Do not ask about today again for each product. Each product starts at its attempt 1 and has its own persuasion attempts.
3. Always propose amounts yourself; first the full past-due amount. Never ask how much they can pay.
4. A date or amount the customer proposes is never a refusal. Check it against that product's facts: today or later, a business day, not after that product's deadline. Weekend or holiday not after the deadline: offer the next business day. After the deadline: say the latest date you can record is the deadline and offer it; refusing the deadline is a flat refusal. Vague period: ask once for the exact day; if none, propose the deadline. "Next Friday" = Friday of the following calendar week.
5. If they name one date for everything and it is after one product's deadline, that product goes on its own deadline: say so in the read-back. The others keep the date they named.
6. Full amount too much for a product: make ONE offer that names that product's floor and its attempt 1 date together ("I can accept the minimum payment of <floor> dollars; the rest stays overdue. Could you pay that on <date>?"). That offer is attempt 1. Never name that floor again except in attempt 2 on the deadline. Floor up to full amount: accept. Below the floor: say it cannot be recorded and offer the floor once.
7. A flat refusal uses one attempt for that product. When a product's attempts are used up, stop for that product and CALL add_note with that product_id and reason refused. Do not repeat a refused offer.
8. Read all agreed promises back together (product, amount, date each) and ask "Do you confirm?" once. After a clear yes, CALL create_promise once per product, one call per message.
9. After the promises are recorded, say "You will receive a text message confirming this promise."
10. Every product without a promise gets one add_note with its product_id and a reason: refused, hardship, dispute, paid or service_error. Then thank them, say goodbye and CALL close_call (outcome promise if any promise was recorded; the bank system corrects the outcome from the records).
Other situations:
- Illness, a death in the family or job loss: one short sentence of sympathy, no persuasion. Offer the customer support team. If they accept, CALL transfer_to_agent with queue support (no notes at all on a transfer). If they decline, note each product without a promise with reason hardship, goodbye, close_call with outcome no_promise and reason hardship.
- "Already paid" or "not mine" on one product: say payments can take one business day to appear (paid) or do not argue (dispute), note that product (paid or dispute) and continue with the others.
- A new payment plan or lower instalments: do not describe a plan. CALL transfer_to_agent with queue restructuring. No notes at all on a transfer.
- A request for a human: ask once whether you can help first. If they insist, CALL transfer_to_agent with queue general. No notes.
- A recorded promise cannot be changed or cancelled in this call; the mobile app can.
- If create_promise fails twice for a product: keep the recorded ones, CALL add_note with reason service_error for that product."""


# ----------------------------------------------------------------- the workflow


def build(brief):
    api = wf.ToolAPI(ROOT / "tools" / "openapi.json")
    multi = brief == "B"
    cust = {"customer_id": "{{customer_id}}"}

    def close_tool(outcomes, reasons):
        return wf.api_tool(api, "close_call", description="End the call with the outcome. CALL it last, after saying goodbye. Nothing is accepted after it.",
                           model_fields=("outcome", "reason"), baked=cust, enums={"outcome": outcomes, "reason": reasons},
                           field_help={"reason": "Required except for promise and paid."},
                           pre_code=(CLOSE_GUARD_B if multi else CLOSE_GUARD_A), hook_rules=CLOSE_HOOK)

    def transfer_tool(queues):
        return wf.api_tool(api, "transfer_to_agent", description="Hand the call to a person. CALL it only in the situations your task names.",
                           model_fields=("queue",), baked=cust, enums={"queue": queues}, hook_rules=TRANSFER_HOOK)

    to_end = wf.when_true("end", "close_call succeeded", "close_call_response.data.ok")
    nodes = {}
    nodes["setup"] = wf.code_node("setup", SETUP, "opening")
    nodes["opening"] = wf.conversation(
        "opening", OPENING,
        # BRIEF A rules 1-2: required first sentence and the confirmation question.
        on_enter=wf.say("Hello, this is the digital assistant of Freya Bank. We keep a recording of this call. Am I speaking with {{title}} {{last_name}}?"),
        # BRIEF A outcome table: only the outcomes possible before identity is checked.
        tools=[close_tool(["not_reached", "not_verified", "transferred"], ["unclear", "wrong_number", "deceased", "declined", "human"]),
               transfer_tool(["general"])],
        extraction=[wf.extract("who", "string", "Who is on the line, from their last message. customer: they clearly confirmed they are the named person (yes, that's me, speaking, or their own name). someone_else: they are another person, for example a relative, and the customer exists. Empty if not clear yet.",
                               enum=["customer", "someone_else"], confidence=0.7)],
        transitions=[to_end,
                     wf.when_any("identity", "The customer confirmed who they are", ("who", "equals", "customer")),
                     wf.when_any("third_party", "Someone else answered", ("who", "equals", "someone_else"))],
        max_turns=8)
    nodes["third_party"] = wf.conversation(
        "third_party", THIRD_PARTY,
        tools=[wf.api_tool(api, "schedule_callback", description="Book a callback. CALL it when the person gives a day and a time inside the allowed window.",
                           model_fields=("date", "time"), baked=cust,
                           field_help={"date": "Callback date as YYYY-MM-DD.", "time": "Callback time as HH:MM, 24 hour."}, hook_rules=CALLBACK_HOOK),
               close_tool(["not_reached"], ["callback", "no_callback", "wrong_number", "deceased", "unclear"])],
        transitions=[to_end], max_turns=12)
    nodes["identity"] = wf.conversation(
        "identity", IDENTITY,
        on_enter={"type": "llm", "prompt": "Thank them and ask for their date of birth, for security."},
        tools=[wf.api_tool(api, "verify_identity", description="Check one security answer. CALL it every time the customer gives an answer.",
                           model_fields=("field", "answer"), baked=cust,
                           field_help={"answer": "date_of_birth as YYYY-MM-DD (convert words to digits; numbers-only dates are day, month, year). phone_last4 as four digits."},
                           hook_rules=VERIFY_HOOK),
               close_tool(["not_verified", "transferred"], ["failed", "declined", "human"]),
               transfer_tool(["general"])],
        transitions=[to_end,
                     wf.when_true("fetch_account", "Both security answers verified", "verify_identity_response.data.all_verified")],
        max_turns=14)
    nodes["fetch_account"] = wf.action_node(
        "fetch_account", wf.api_action(api, "get_account", baked=cust, hook_rules=ACCOUNT_HOOK, retries=2), "negotiate")
    neg_tools = [
        wf.api_tool(api, "create_promise", description="Record one payment promise. CALL it only after the customer said a clear yes to your read-back.",
                    model_fields=("product_id", "amount", "date"), baked=cust,
                    field_help={"product_id": "The product id from the account facts, for example p1.", "amount": "Amount in dollars, a number.",
                                "date": "Promise date as YYYY-MM-DD."},
                    pre_code=PROMISE_GUARD, retries=1,   # a 500 recorded nothing and may be repeated (tool API); brief: try once more
                    hook_rules=PROMISE_HOOK % (" CALL add_note with that product_id and reason service_error, then continue." if multi else
                                               " Say goodbye and CALL close_call with outcome no_promise and reason service_error.")),
        transfer_tool(["restructuring", "general", "support"]),
        close_tool(["promise", "paid", "transferred", "no_promise"], ["refused", "hardship", "dispute", "service_error", "restructuring", "human", "support"])]
    if multi:
        neg_tools.insert(1, wf.api_tool(api, "add_note", description="Record why one product ended without a promise. CALL it once for each product that gets no promise, except when the call is transferred.",
                                        model_fields=("product_id", "reason"), baked=cust, hook_rules=NOTE_HOOK))
    nodes["negotiate"] = wf.conversation(
        "negotiate", NEGOTIATE_B if multi else NEGOTIATE_A,
        on_enter={"type": "llm"}, tools=neg_tools, transitions=[to_end], max_turns=40)
    nodes["end"] = wf.end_node("end", "call_closed")
    return {"initial_node": "setup", "system_prompt": SYSTEM, "nodes": nodes, "global_nodes": {},
            "test_variables": {"customer_id": "c_test", "first_name": "Daniel", "last_name": "Reyes", "title": "Mr", "now": "2026-10-14T11:00"}}


if __name__ == "__main__":
    brief = (sys.argv[1] if len(sys.argv) > 1 else "A").upper()
    w = build(brief)
    problems = wf.lint(w, wf.ToolAPI(ROOT / "tools" / "openapi.json"))
    out = ROOT / "out" / ("ref-%s.workflow.json" % brief.lower())
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(w, indent=1), encoding="utf-8")
    print("lint:", problems or "clean", "->", out)
    if problems:
        sys.exit(1)
    if "--save" in sys.argv:
        import freya
        print(json.dumps(freya.save_workflow("ref-" + brief.lower(), w)))
