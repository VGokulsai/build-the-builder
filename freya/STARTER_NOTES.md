# Freya workflow format (read from the starter, 10 Oct 2026)

Source: GET /api/v2/workflow/{id}?workspaceId=... on staging-app.freyavoice.ai
(needs header `x-workspace-id: <workspaceId>` plus the signed-in session).
Starter: "Freya Bank Collections Base (2 nodes)" - "Minimal two-node collections agent on
freya-bank-mock: identity check, then payment promise. Base for hackathon builds."

## Shape
```
workflow:
  initial_node: "identity"
  system_prompt: ""                      # global, empty in starter
  global_nodes: {}
  nodes:
    <name>:
      name, node_type: "conversation"
      on_enter: {type: "tts", text: "Hello ... {{title}} {{last_name}}?"}   # spoken on entry
      task_message: "<the node's prompt>"  role_message: ""
      tools: [ {type: "function", config: {timeoutMs, maxRetries},
                function: {name, handler: "__function__:api_call" | "__function__:end_call",
                           description, parameters: {type: object, properties: {
                             url: {default: <mock url>}, method: {default: POST},
                             headers: {...}, body: {type: object, required: [...],
                               properties: {x: {type, default: "{{x}}", description, enum?}}}}}}} ]
      transitions: [ {description, target_node,
                      condition: {logic: "or"|"and", conditions: [
                        {variable: "verify_identity_response.data.all_verified",
                         operator: "equals", operand: "true", mode: "exact"}]}} ]
      max_node_turns: 80, interruptible, assertions: [], pre_actions: [], response_mapping: [],
      extraction_schema: [], truncation_strategy: "keep_all", suppress_tool_results: false ...
  tools: [ global tools, e.g. close_call with config.alwaysRunsAt: ["end_of_call"] and
           pre_process_code: python run on the call config before sending ]
  agent_config:
    llmConfig: {model: "experimental-5", provider: "experimental-5", temperature: 0.7, maxTokens: 1000,
                firstMessage, systemPrompt, firstMessageMode: "assistant-speaks-first", tools: [end_call]}
    sttConfig: {model: freya-stt, language: "tr" !!}   ttsConfig: {model: freya-tts, voiceId: leyla, language: "tr" !!}
    callTimeoutSettings: {silenceTimeout: 10, maximumDuration: 600}
  test_variables: {now: "2026-10-14T11:00", title: Mr, last_name: Reyes, first_name: Daniel,
                   customer_id: "c_7f426f63-913", test_caller_phone_last4: "4471",
                   test_caller_date_of_birth: "1988-03-14"}
```

## Mock backend (real HTTP, usable from local tests)
https://freya-bank-mock.freyavoice.workers.dev/v1/{verify_identity, get_account, create_promise, close_call}
- verify_identity body: {field: date_of_birth|phone_last4, answer, customer_id}; response has data.all_verified
- get_account body: {customer_id} -> late products (product_id like p1)
- create_promise body: {product_id, amount, date YYYY-MM-DD, customer_id}
- close_call body: {outcome: promise|no_promise|not_verified|not_reached, reason, customer_id}
  reason: no_promise -> refused; not_verified -> failed|declined; not_reached -> wrong_number|unclear

## Starter prompts (task_message)
identity: verify only; ask DOB, then phone last 4, verify_identity per answer; don't explain why
calling until verified; on failure say goodbye ending "Have a good day."
collection: call get_account first, state past-due amount, ask when they can pay, read back amount
+ date, create_promise after yes; goodbye ending "Have a good day." Now: {{now}}.
"Have a good day." triggers end of call (end_call trigger_pattern).

## Things to check
- STT/TTS language is "tr" (Turkish) while prompts say English: likely wrong for English tasks.
- Likely graded on close_call outcome + backend state (promise recorded, verification) via the mock.

## Probed 10 Oct ~15:50 IST
- verify_identity is stateful per customer: all_verified turns true only after both answers; wrong_answers_left starts at 3.
- get_account (starter customer): p1 credit_card 4821, past_due 420, days_late 6, minimum_payment 126.
- unknown customer_id -> {"ok":false,"error":"unknown customer_id"}. No public reset/create endpoints (/v1/reset etc. 404); the kit's tool API doc should say how cases are set up.

## Rules page (pasted by Gokul)
- Hidden briefs open Sun 17:00 UTC (22:30 IST), close Sun 20:00 UTC (01:30 IST Mon). Run builder once per brief, fix crashes only, submit agents + code + builder trace.
- Builder: one command, brief in, Freya workflow out, no hand edits. 60 hidden cases, pass/fail (bank records right AND conversation followed brief). Tie-break: build time.
- Seven fixed tool names; fields/allowed values may change. Calls in English text; `now` variable drives every date rule. Same Freya model for all agents.
- No hidden-brief content may be written into the builder.
