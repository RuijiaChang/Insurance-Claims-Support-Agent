# SOP-Guided Insurance Claims Agent design

This is the English version of the engineering design dated November 25, 2026. It covers the public system design and reflects implementation details where they differ from the initial proposal.

## 1. Intent and context

Build a conversational insurance-claims support agent whose behavior follows a fixed business workflow. Reviewers should be able to trace each requirement to code and tests, run the demo locally, and observe which decisions come from policy and which come from language understanding.

## 2. Goals and scope

1. Enforce the four phases in code: `VERIFY_ID → RESOLVE_INTENT → PROCESS_CASE → POST_PROCESS`.
2. Match at least three distinct identity fields, handling partial answers, refusals, corrections, and alternate fields while protecting claim details.
3. Record early case hints, intent, and email preferences for use in later phases.
4. Interpret messy language, clarify ambiguity, and give grounded answers through bounded processing paths.
5. Offer an optional email summary with the discussion, outcome, and next steps.
6. Redirect unrelated requests and offer human help after repeated attempts.
7. Recognize emotion, de-escalate, explain gates, suggest alternatives, and escalate when persuasion should stop.
8. Support fixture-specific features such as representatives and consent, aliases, national IDs, claim scoring, document-name mappings, follow-up guidance, and appeal deadlines.
9. Deliver a React chat, two ways to supply a model token, Docker startup, and engineering documentation.

The English-only demo uses read-only fixtures and mock adapters for consent, email, and handoff. Sessions have an in-memory lifetime. Voice, accounts, production CRM integrations, and durable session storage are outside the project scope. Private fixture data stays outside pre-verification model context. Generic failures prevent field-by-field probing and account discovery. Model errors fall back to usable responses, and collected information should carry forward through the conversation.

## 3. Constraints

The stack is Python 3.12, FastAPI, Pydantic v2, the OpenAI SDK, React, Vite, TypeScript, and Docker. The repository uses six unmodified fixture JSON files under `apps/insurance_claims/fixtures/`. A hosted operator can supply a centrally managed model key with provider-side spending controls and in-process rate limits. Callers can supply their own keys.

## 4. Approaches considered

| Approach | Design and trade-off |
| --- | --- |
| A. Explicit state machine with model extraction and phrasing | Code merges memory, checks gates, applies phase transitions, limits context, and checks output. Bounded tool calling is available during case processing. Most turns use two model calls and need explicit orchestration. |
| B. Single agent with gated tools | A free-running model chooses operations and each tool validates authorization. Tool checks alone leave phase order dependent on the agent's interpretation. |
| C. Graph framework | A graph expresses the same transitions with framework components and adds a dependency and abstraction layer. |

Approach A makes phase ownership and data access explicit and independently testable. It leaves interpretation and language generation to the model.

## 5. System structure

React renders Chat and the SOP Inspector. JSON REST connects it to FastAPI, with optional per-request model credentials. The session store maintains in-memory state and per-session serialization. Under `backend/app/`, `sop/` owns phase policy and turn orchestration, `llm/` owns model calls and prompts, `guards/` checks replies, `tools/` implements bounded operations, `data/` loads fixtures, and `config/sop.yaml` sets policy thresholds. The Docker image packages the API and compiled frontend together on port 8000. [Architecture](ARCHITECTURE.md) describes the runtime path.

## 6. State model

`SessionState` carries the session ID, phase, substate, caller role and representative details, and per-field identity evidence with statuses and source turns. `verified_party_id` names a matching policyholder. `access_granted` independently gates data. The state tracks verification failures and the last comparison fingerprint, consent scenario/status/polls, memory slots, active and discussed cases, primary and current-turn intent, pending handoff, case log, counters, pending question, email decision and preview, mock ticket, transcript, and decision events.

The intent vocabulary covers denial questions, status inquiries, document submission, next steps, general claim questions, and payment questions. `HANDOFF` and `CLOSED` are terminal phases.

## 7. Per-turn pipeline

1. Extract meaning from the text using the current phase, pending question, and previous agent message. Reconcile with deterministic regex extraction.
2. Merge evidence and memory once for the turn.
3. Apply global guards and run the current policy to construct the turn plan, including directives, quick replies, and validated transitions.
4. Build context from permitted facts for the final stage.
5. Generate a response, with at most three tool iterations during case processing.
6. Screen the response, retry once after a guard violation, then fall back to a template if needed. Retain state and events for inspection.

A turn may use the same extraction across up to three followed phase hops (`max_hops`), so at most four phase handlers run. The plan accumulates directives. Access checks run against the resulting state, so a successful verification turn can immediately answer an identifiable case. The [architecture invariants](ARCHITECTURE.md#invariants) state which component owns transitions, which data can enter context, which tools can run, and what the responder can use.

### 7.1 Extraction

Structured extraction covers identity fields, caller and representative roles, case hints, intent, normalized question, user acts, scope, emotion, and email preference. Acts include giving or refusing information, asking why, clarifying, requesting a human, confirming, denying, selecting a case, asking a question, ending, making an email decision, and attempting bypass. Scope distinguishes claim questions, general insurance support, small talk, and unrelated requests.

Regex handles dates, phones, emails, contextual ID suffixes, and policy and case IDs. ID suffix detection distinguishes dates and embedded case or policy digits. Ambiguous numeric dates can produce two candidates for one field. Regex takes precedence on formatted fields and supports fallback after extraction errors. Identity values used in comparison must come from caller-supplied evidence.

### 7.2 Memory

Hints, intent, preference, role, and useful user text can arrive early. Slots track where they were captured and used. Corrections replace the current slot value while retaining history. A verification reply can acknowledge the caller's own claim description without reading a record. The Inspector shows safe provenance across phases.

## 8. Phase policies

### 8.0 Global checks

An explicit human request takes priority. For an unrelated question, politely decline and return to the current step. After three such turns, offer a human and continue declining unrelated content. General insurance questions can be answered from field definitions or default guidance. Small talk gets a brief response without raising the off-topic counter. A bypass attempt adds recovery directives and conveys no authority. Independently valid identity input in the same message can still satisfy the gate. Emotion contributes empathy and recovery directives before phase-specific instructions.

### 8.1 Identity verification

Collect name, date of birth, phone, email, and ID last four. Policy number locates accounts. Candidate lookup tries a known policy number, fuzzy name and aliases, then phone or email. Name matching normalizes text. DOB compares parsed dates. Phone uses E.164 normalization, email is case-insensitive, and the ID field accepts SSN or national ID suffixes.

Ask for the remaining count based on distinct provided fields, excluding refused fields. Compare only once the caller has provided at least three fields. An account passes when three or more fields match and each additional supplied field has a matching value. Historical values can satisfy a field, and an ambiguous date still counts once. Generic failure language and redacted statuses protect account existence and which values matched. A materially new unsuccessful comparison counts as one failure. The third failed comparison locks the flow and triggers mock handoff.

Explain the gate when asked. Offer alternate fields on refusal, and offer human help when too few usable options remain or the persuasion budget is spent. The pre-access fact pack contains safe procedural facts and caller-supplied hints.

Representatives supply the policyholder's evidence plus their own name and relationship. Normalize relationships to the representative's relationship to the policyholder. Match that relationship and name against registered representatives for the matched buyer. An unregistered representative gets a refusal with options to end or transfer. A registered representative starts simulated consent against the policyholder's registered contact. Pending consent leaves access off. The browser polls every four seconds without overlapping a turn. User messages may also advance the mock sequence. Approval opens access and moves to intent resolution. Timeout offers one resend, transfer, or end. Poll events use a deterministic response path without replaying prior user extraction.

### 8.2 Intent and claim resolution

After access, look only at the matched policyholder's summaries. Score an exact claim ID 100, type 3, status 3, month 2, and year 1. A top score of at least 3 with a lead of 2 or more selects the claim. “Denied healthcare January” scores CL-2048 at 8 and CL-2011 at 5. “January healthcare” scores both at 5 and leads to a clarification.

A unique result sets the active case, records it as discussed, and advances immediately. Infer intent from the remembered intent or case hints. Ties prompt the caller to choose. Missing hints prompt for the caller's need. A missed match offers available claims or human help. An empty list is reported directly. The model interprets the description and phrases the question, while the scoring rule produces repeatable choices.

### 8.3 Claim processing

The fact pack contains the active claim, relevant schema definitions, mapped document names, deadline facts, and appropriate guidance. The read-only registry can supply document requirements, document alternatives, follow-up guidance, and field definitions. Each call passes the stage, access, and ownership checks applicable to it. Case switching and human handoff are policy transitions triggered by extracted intent or typed actions.

Guidance first filters by document eligibility. It chooses the longest matching phrase, excludes time-ago phrasing from duration matches, breaks ties with turn intent, and can use a supported topic supplied by the model. A claim with outstanding documents can receive the fixture fallback. A claim with no outstanding documents receives only applicable guidance and case facts. Material alternatives and an escalation option address unavailable documents. Guidance fills claim, document, and processing-time placeholders. Document aliases map the pathology report and office note to canonical keys. A fuzzy match can resolve other names, with default guidance available when mapping fails.

Compute deadline status relative to the configured clock. Offer human review if a deadline has passed. Ground replies in the fact pack, tool results, and caller statements. Record disclosed facts and next steps in the case log for the summary. A completion request moves to follow-up. A case switch re-enters resolution and can immediately return to processing.

### 8.4 Post-processing

Offer to send a summary to the masked registered email, accounting for an earlier preference. When accepted, preview the structured subject, discussion, claim status and outcome, next steps, and contact information. The email composer uses the case log and validated facts, with a grounded draft available as fallback. Confirming writes a mock message to the Outbox and can emit an `.eml` file when configured. Skipping closes without a message. A pending transfer runs after the email decision.

Delivery is restricted to the registered policyholder address. An alternate address request receives an explanation and a way to seek help. An additional claim question can return to processing.

### 8.5 Legal phase transitions

| Source | Allowed destination phases |
| --- | --- |
| VERIFY_ID | RESOLVE_INTENT, HANDOFF, CLOSED |
| RESOLVE_INTENT | PROCESS_CASE, POST_PROCESS, HANDOFF, CLOSED |
| PROCESS_CASE | RESOLVE_INTENT, POST_PROCESS, HANDOFF |
| POST_PROCESS | PROCESS_CASE, HANDOFF, CLOSED |
| HANDOFF and CLOSED | Terminal |

### 8.6 Handoff

Lockout transfers automatically. An explicit transfer request before access creates a mock ticket at once. With access, offer the email summary first. Persistent off-topic requests, consent timeout, unregistered representatives, exhausted de-escalation, missing material alternatives, expired deadlines, and missing case facts can prompt an offer. The ticket records an identifier, reason, verification status, caller intent, and an active case ID only when access is granted.

## 9. Emotional support and SOP recovery

Extract an emotion label and intensity on each turn. Track consecutive negative emotion and persuasion attempts by gate. L1 acknowledges the caller's feelings and continues. L2 gives empathy, a brief reason for the requirement, acceptable options, and a concrete next step. L3 stops persuasion and offers a transfer after two persuasion attempts, a high-intensity streak, or abusive language. A caller who declines escalation gets a brief restatement and can still choose human help. Anxious callers benefit from knowing what will happen next, confused callers from simple steps, and angry callers from concise, specific acknowledgment. Emotion leaves access and phase rules intact.

## 10. Model providers

The OpenAI-compatible client supports OpenAI, DeepSeek, and Custom presets. Providers that support structured outputs and tools use those capabilities. Other providers use JSON-mode extraction with validation and deterministic guidance preparation. The default models are `gpt-4.1-mini` for OpenAI and `deepseek-chat` for DeepSeek; `gpt-5*` models need OpenAI organization verification and receive `reasoning_effort` instead of `temperature`. Provider configuration comes from server environment variables or request headers. A browser key takes precedence and uses its own provider settings. A server key works only with the server's configured provider and model.

Custom URLs require HTTPS and publicly resolving addresses. The validation route sends a short model request to test the supplied credentials. The key stays in browser session storage when provided via UI. The backend keeps keys out of normal application logs and error payloads.

The default server-key limits are 20 messages per IP per minute, 300 per IP per day, and 3,000 globally per day, with a 60-turn session cap. Over-budget demo requests can switch to a caller-supplied key. The model client uses a 20-second timeout and bounded retries. Error handling distinguishes authorization, rate limits, timeouts, and other failures. Prompts live in `llm/prompts/`, with shared instructions and stage-specific directives.

## 11. Output guard

Before access, compare generated text against sensitive fixture tokens, accounting for information from the caller. During claim processing and follow-up, compare extracted amounts, dates, and case identifiers to allowed facts, tool results, and caller text. Normalize numbers and common date formats. Also check sensitive identity echoes. Retry once with sanitized feedback, fall back to a template when needed, and record the outcome in the timeline. These checks cover specific patterns and complement context restriction.

## 12. HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Process health |
| GET | `/api/config` | Model and demo configuration, without secrets |
| POST | `/api/config/validate-key` | Check caller-supplied provider credentials |
| POST | `/api/sessions` | Start a session with a consent preset |
| POST | `/api/sessions/{id}/messages` | Process text or a typed quick-reply action |
| POST | `/api/sessions/{id}/events` | Process a consent poll |
| GET | `/api/sessions/{id}/state` | Read a redacted snapshot |
| GET | `/api/sessions/{id}/transcript` | Export conversation and events |
| GET | `/api/sessions/{id}/outbox` | View simulated sent mail |
| DELETE | `/api/sessions/{id}` | Delete the current session |

Typed actions take priority over model classification. Trimmed text must be nonempty and fit the 4,000-character limit. Sessions return 404 after expiry and the UI can recreate them. The default lifetime is two hours. A per-session lock serializes turns and consent events. Horizontal scaling would need shared storage and coordinated locking and quotas.

## 13. Frontend

A React reducer manages chat, request state, and the Inspector. The top bar contains the scenario and consent selectors, reset, demo date, and model settings. Nine presets prefill openers. The frontend supplies phase-based suggestion chips. Server-supplied quick replies send typed actions. The Inspector has state, memory, timeline, and Outbox panels and uses a drawer on narrow screens. Model settings supports OpenAI, DeepSeek, and Custom, with an optional model override for every provider, and can test a connection. A reply that fell back to templates because of a model error carries one chat notice naming the cause. It opens when a key is needed, including after a demo quota error.

## 14. Configuration

`sop.yaml` centralizes policy thresholds. Defaults include three matched fields, three failed comparisons before lockout, a 90-point name threshold, three off-topic questions before an offer, two persuasion attempts, a three-turn emotion streak, four-second consent polling, one resend, three tool iterations, three hops, and an 85-point document threshold.

Environment variables configure the provider, key, default model, base URL, fixture path, optional outbox path, proxy trust, and demo date. The session lifetime is set by `session.ttl_min` in the SOP configuration file. `SOP_CONFIG_PATH` selects that file. Compose defaults the demo date to March 5, 2026, so reviewers can exercise deadlines relative to the fixture timeline.

## 15. Quality attributes

Context isolation, redacted snapshots, sanitized errors, and output checks protect fixture data. Deterministic phase tests and model-double scenarios verify gate behavior. An event timeline exposes extraction, policy, tool, and guard decisions. Bounded model calls support the design target of a median turn below four seconds. Live latency depends on the model and network. Docker, the health endpoint, and the Render configuration support deployment. Ruff, mypy, typed APIs, and the module structure support maintenance.

## 16. Verification

Unit tests cover normalization, aliases, candidate search, evidence counting, claim ranking, guidance, dates, tool permissions, and guard decisions. Scripted scenario tests exercise Margaret's flow and ambiguity, partial or repeated evidence, account probing, lockout, emotional recovery, representative approval and timeout, missing registration, out-of-scope routing, email skip, case switching, injection attempts, missing claims, no-document guidance, and handoff after an email decision. API tests cover input boundaries, concurrent polls and messages, provider URL validation, and server-key limits. Frontend tests cover reducer, APIs, presets, and interaction behavior.

CI runs static checks and tests without a model key. Eight YAML scripts drive live evaluation with assertions for state, claim selection, and protected output. The runner writes a [Markdown report](../backend/evals/results/REPORT.md) with the model, outcomes, and guard counters.

## 17. Delivery

The [README](../README.md) explains Docker and local startup, token configuration, presets, and limits. [Architecture](ARCHITECTURE.md) explains control flow and invariants. [Demo script](DEMO_SCRIPT.md) gives the inputs and expected behavior for all nine presets. [Requirements trace](REQUIREMENTS_TRACE.md) connects assignment requirements to implementation and tests. The Docker repository satisfies local delivery, and `render.yaml` supplies the configuration for an operator-hosted deployment.
