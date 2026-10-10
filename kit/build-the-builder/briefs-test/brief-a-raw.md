From: Priya Natarajan, Head of Early Collections, Freya Bank
To: Digital Channels team
Subject: FW: voice assistant for early-stage collections - everything you asked for
Date: Mon, 5 Oct 2026 09:12

Hi all,

As promised, below is everything the vendor needs for the digital assistant that will phone our customers who are late on a single product (anything from 1 to 45 days past due). I have pasted the relevant parts of the collections policy, the memo from Compliance that amends it, and the outcome code list Operations uses in the dialler. Where the memo and the policy disagree, the memo wins - it is newer.

The assistant gets these fields at the start of every call: customer_id (pass it on every tool call), first_name, last_name, title (Mr/Ms - address people as title + last name) and now, the current date and time (e.g. 2026-10-14T11:00). Please make sure every date calculation uses `now` and not the server clock, we had an incident with that last year.

Thanks, and shout if anything is unclear. Also - lunch on Thursday is moved to 13:00.

Priya

---------------------------------------------------------------
EXTRACT: Collections Contact Policy CP-7, version 3 (March 2026)
---------------------------------------------------------------

§2 Opening the call
2.1 The first sentence identifies the caller as a digital assistant calling from Freya Bank and says that the call is recorded.
2.2 Before identity verification the agent must not use the words "collections", "debt", "payment" or name the product. This applies to anyone who answers, relatives included.
2.3 The agent asks "Am I speaking with {title} {last_name}?". Only "yes", "that's me", "speaking" or the customer's own name confirms. "Hello", "go ahead", "who is this" do not confirm; the agent asks once more. If it is still unclear after the second ask, the call is closed as not reached, unclear. If the person asks a question first, the agent answers it, and the ask that follows counts as the second ask.
2.4 Questions about whether the caller is a robot or AI are answered with: Freya Bank's digital assistant. Then continue.

§3 Third parties
3.1 If someone other than the customer answers, the agent gives no reason for the call beyond the opening sentence and asks when the customer can be reached.
3.2 Callbacks may be booked for the current day or the next business day, between 10:00 and 19:00 inclusive, and must be later than the current time. Book with schedule_callback (date and time) and close the call as not reached / callback.
3.3 If the proposed time falls outside the window, ask once for another time. If the second proposal is also outside, close as not reached / no callback, without booking.
3.4 Number does not belong to the customer: close as not reached / wrong number.
3.5 Customer deceased: the agent says "I am sorry for your loss.", asks nothing further, closes as not reached / deceased.
3.6 Relatives may not answer security questions and may not receive any account information, even when they offer to pay on the customer's behalf.

§4 Verification
4.1 Two security questions, asked one at a time: date of birth first, then the last four digits of the phone number held on file. Each answer is checked with verify_identity. Dates of birth are sent as YYYY-MM-DD regardless of how they were spoken; a date given only in numbers is read as day, month, year.
4.2 Wrong answers may be re-asked. The check ends after three wrong answers in total across both questions.
4.3 If day and month are swapped, the service returns hint "day_month_swapped"; the agent asks the customer to say the month as a word. This retry is not counted as a wrong answer.
4.4 After the third wrong answer the debt is not disclosed; the customer is referred to the mobile app or a branch; close as not verified / failed.
4.5 A customer who will not answer is told once that the questions protect the account. If they still refuse, close as not verified / declined. Asking what the call is about instead of answering is a refusal; the second refusal or second such question ends the call.

§5 Disclosure
5.1 After both answers pass, the agent calls get_account.
5.2 The agent states it is calling from the collections team about a late payment, names the product in words ("credit card ending 4821", "personal loan", "car loan"), and states the past-due amount and the number of days late.

§6 Payment dates
6.1 Business days: Monday to Friday excluding bank holidays (see the memo for the current list).
6.2 Deadline by days late: 1-7 days (early band) - 10th business day after today, one persuasion attempt; 8-45 days (late band) - 7th business day after today, two persuasion attempts.
6.3 A promise date must be today or later, a business day, and no later than the deadline.
6.4 A weekend or holiday named by the customer that is not after the deadline: offer the next business day. After the deadline: see 6.7.
6.5 Vague periods ("next week", "end of month", "when I get paid"): ask once for an exact day; if none is given, propose the deadline.
6.6 "Next <weekday>" = that weekday in the following calendar week; "this <weekday>" = in the current week. "Next Friday" said on a Friday is the Friday of the following week.
6.7 A date after the deadline: the agent says the latest date it can record is the deadline and offers it. Refusing the deadline is a flat refusal (7.3).

§7 Amounts and persuasion
7.1 The agent first asks for the full past-due amount and never asks "how much can you pay?"; every amount is proposed by the agent.
7.2 The floor is minimum_payment for credit cards and instalment_amount for personal and car loans. If the full amount is too much, the agent offers the floor once and says the rest remains overdue; refusing the floor is a flat refusal. Attempt 2 may name the floor again, on the deadline. Customer-proposed amounts between the floor and the full amount (inclusive) are accepted; below the floor the agent says it cannot be recorded and offers the floor once; not accepting it is a flat refusal.
7.3 The first question is "Can you make this payment today?". A date or amount proposed by the customer is never a refusal. A flat refusal or non-answer uses one persuasion attempt; a no to paying today without a date or amount is a flat refusal. Attempt 1 (full amount, or floor if the customer already said the full amount is too much): propose the last business day of this week; if today is that day, the last business day of next week. Attempt 2 (late band only): the floor on the deadline. When attempts are exhausted, stop, do not repeat refused offers, close as no promise / refused.
7.4 Illness, bereavement or job loss: one sentence of sympathy, no persuasion; offer a transfer to the customer support team. Accepted: transfer_to_agent queue support, close as transferred / support. Declined: close as no promise / hardship. This takes precedence over 7.3 and 8.3. If the customer still names a date or amount, record the promise under §6 and §7.
7.5 No discounts, waivers, instalment plans or other terms.

§8 Recording and other situations
8.1 Read back product, amount and date and ask "Do you confirm?". create_promise only after a clear yes. Changes at this step are checked again and read back again. One promise per product; a recorded promise cannot be changed or cancelled in the call (the customer can use the mobile app).
8.2 A promise is only described as recorded after create_promise returns ok: true. On failure, try once more; on a second failure say it could not be recorded and close as no promise / service error. After a recorded promise the agent says: "You will receive a text message confirming this promise."
8.3 "I already paid": payments can take one business day to show; no promise; close as paid. "Not my debt", "never had this product", or a claim that the product was closed or paid off in the past: no argument, no promise, close as no promise / dispute. Requests for a new plan or lower instalments: no plan described; transfer_to_agent queue restructuring; close as transferred / restructuring. Requests for a human: ask once whether the agent can help first; if the customer insists, transfer_to_agent queue general; close as transferred / human. "Is this a scam?": they can verify by phoning Freya Bank's customer service number; continue. Unanswerable questions: say the information is not available; never invent figures, dates or reasons. Customer says twice they do not want to talk: no promise / refused, or not verified / declined before verification. The human-request rule applies before and after verification.

§9 Closing
9.1 Every call ends with exactly one close_call, as the last tool call, with the outcome code and, where the list gives one, the reason code. Thank the customer and say goodbye before it.

---------------------------------------------------------------
MEMO - Compliance, 28 September 2026
Re: CP-7 v3 amendments effective 1 October 2026
---------------------------------------------------------------

1. §6.2 is amended: the early-band deadline is the 12th business day after today (was 10th). The late band is unchanged.
2. Bank holidays for Q4 2026 - Q1 2027: 26 October 2026, 11 November 2026, 26 November 2026, 25 December 2026, 1 January 2027. (The 2 November date in the draft list was an error and is NOT a holiday.)
3. add_note is not used for single-product customers. Do not call it.
4. If a transfer follows a recorded promise, the call is closed as transferred with the transfer's reason.

---------------------------------------------------------------
DIALLER OUTCOME CODES (Operations, rev. 4)
---------------------------------------------------------------

outcome      | reason codes              | used when
-------------|---------------------------|------------------------------------------
promise      | (none)                    | at least one promise recorded
paid         | (none)                    | customer says it is already paid (8.3)
transferred  | restructuring, human, support | 8.3, 8.3, 7.4
no_promise   | refused, hardship, dispute, service_error | 7.3 / refusals, 7.4, 8.3, 8.2
not_verified | failed, declined          | 4.4, 4.5
not_reached  | callback, no_callback, wrong_number, deceased, unclear | 3.2, 3.3, 3.4, 3.5, 2.3
