# Spec: Freya Bank statement debt (final)

Sources: analysis 8 Oct (A), decisions recap mail 9 Oct (R, overrides A), follow-up session 10 Oct (S, overrides both), service contract 1 Oct (C), example-scenarios (E).

1. Variables: `customerNumber` (8 digits, never asked), `now` (Istanbul time; every date decision) — BRIEF.md, README.
2. Opening: caller already identified by IVR; no PIN/date-of-birth questions (A 2). Turkish only (BRIEF).
3. Someone else's card: no info, security, back to IVR login (A 8.6, E5).
4. Identity: not in brief (IVR did it).
5. Card selection: 1 card → no question; several → "Hangi kartınızın borcunu..." with ≤2 own names; same name → last four → last six → full number (A 3.2, R 4); supplementary not eligible; "all cards" costs a try (A 3.3, E3). Only last four digits ever spoken, digit by digit (R, A 4.9).
6. Reading order and sentences: A 4.1–4.8; currency names in full (R 6, S); no-statement card: "Kartınızın henüz kesilmiş bir ekstresi olmadığı için ekstre borcunuz bulunmamaktadır. İlk hesap kesim tarihiniz ... olacak." (S); cut day: 00.00 sentence first then totalDebt per currency (S); after due: passed, then total; due today: "bugündür".
7. Amounts in words, lira/kuruş, dolar/euro sent, sterlin peni, zero kuruş not said (A 4.9). Dates "21 Ekim 2025".
8. Another card question before the offer (S, A 5.1). Offer depends on registered e-mail (`ibanEmail` non-empty and not Phone-only) (A 5.2). Week-change right: no flag exists (C 5.3) → offered.
9. E-mail: confirm address, short form for messy ones, send only after yes, only latest statement, only registered address, max 3 sends; failures → agent (A 6).
10. Week change: get → tell + ask → options without current week → decide preview → joint-card sentence → confirm, only clear "evet" → change once → done sentence with preview dates (A 7, E2, E5).
11. Endings: table A 10; three tries (A 8.1); silence 3 → close (R 1); out-of-scope asks first (R 2); angry: three calming replies (R correction).
15. Tools: C section 5, envelope `{data, call}` (C 3); `cardNumber` exactly as cards.list returned (C 5). Tool API written to out/final/openapi.json, base URL = our mock + /voice/v1.
