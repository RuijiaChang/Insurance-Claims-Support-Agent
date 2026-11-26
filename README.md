# SOP-Guided Insurance Claims Agent

A conversational insurance claims demo that uses a deterministic SOP to control identity verification, claim access, case handling, and email follow-up.

The Docker setup below is the demo delivery. The repository also includes a Render blueprint for hosted deployments.

## Quick start

With Docker and Docker Compose installed, run from this repository:

```sh
cp .env.example .env
docker compose up --build
```

Open [the chat](http://localhost:8000). The health endpoint is [`/api/health`](http://localhost:8000/api/health). Compose can start with `.env` absent (the optional `env_file` entry needs Docker Compose 2.24 or later). Set `HOST_PORT` if port 8000 is occupied.

Provide an API key in either of two ways:

1. Set `OPENAI_API_KEY` in `.env` before starting. The server uses that key for clients who supply no key.
2. Open **Model settings** in the chat and enter your own key. It takes precedence over the server key. The browser keeps it in session storage and sends it with model requests. Select OpenAI, DeepSeek, or Custom. The optional **Model** field overrides the provider default; Custom requires a public HTTPS base URL and a model name. **Test connection** checks the key and model before you save.

The default OpenAI model is `gpt-4.1-mini`, and the DeepSeek default is `deepseek-chat`. To use another model, set `OPENAI_MODEL` in `.env` for the server key, or enter it in the optional **Model** field of **Model settings** for a browser key. `gpt-5*` models require OpenAI organization verification; an unverified key gets an error, and the chat falls back to basic templates with a notice.

### Local development

Use Python 3.12, uv, and Node.js 20. Run from the repository root:

```sh
(cd backend && uv sync --locked)
(cd frontend && npm ci)
make dev
```

Open [the Vite app](http://localhost:5173). FastAPI runs on port 8000. `LOG_LEVEL` sets the app's log level.

For a one-turn live check of the configured key, run `set -a; . ../.env; set +a; uv run python scripts/smoke.py` from `backend/`.

### Settings and hosting

- `DEMO_TODAY=2026-03-05` anchors relative dates for the January–March fixtures. For example, the March 18 appeal deadline is 13 days away on the default demo date. Change the setting to exercise the expired-deadline path.
- `LLM_PROVIDER`, `OPENAI_MODEL`, and `OPENAI_BASE_URL` configure the server-side model.
- `FIXTURES_DIR` selects the fixture directory. [`sop.yaml`](backend/app/config/sop.yaml) configures verification limits, consent polling, hops, quotas, and the session lifetime under `session.ttl_min`. Set `SOP_CONFIG_PATH` to load a different file.
- For Render, use the included [blueprint](render.yaml), configure `OPENAI_API_KEY` as a secret, and select an account-accessible model. Set appropriate spending controls with the model provider. The built-in server-key limits apply per client IP and globally within the process. Enable `TRUST_PROXY` only behind a proxy that appends the real client address.

## Try the nine presets

Select a scenario to prefill its opener, then press **Send**. Suggestion chips fill the composer. Quick replies execute the indicated action.

1. **Margaret · denied claim** carries an early case hint through verification, selects CL-2048, and offers a follow-up email.
2. **Margaret · frustrated caller** responds to frustration, explains verification, and offers alternative fields.
3. **David · consent approved** requires policyholder verification, representative matching, and approval before access.
4. **David · consent timeout** offers a resend, human handoff, or an end to the session.
5. **Ya Wen · name alias** matches the fixture alias and verifies using email and phone.
6. **Ma Tian · national ID** accepts a national ID suffix as verification evidence.
7. **Ava · no claims** verifies the caller and reports an empty claim list.
8. **Repeated off-topic requests** redirects politely and offers a human representative after three refusals.
9. **Margaret · verification lockout** locks after three failed comparisons and creates a mock handoff.

The [demo script](docs/DEMO_SCRIPT.md) lists the inputs and expected behavior. The [requirements trace](docs/REQUIREMENTS_TRACE.md) maps the workflow, scope control, memory, emotional support, and delivery requirements to code and collected tests.

## Architecture

```text
React chat and Inspector
          ↕ REST
FastAPI and per-session state
          ↓
Extract → merge memory → apply SOP → build context → respond → guard
                              ↓                          ↓
                         fixture tools      approved read-only tools
```

The policy engine owns phase changes and claim permissions. The model extracts meaning and generates language from stage-specific facts. See the [architecture](docs/ARCHITECTURE.md) and [design](docs/DESIGN.md).

## Beyond the baseline

| Feature | Implementation and test evidence |
| --- | --- |
| Representative consent | Registration and simulated consent gate access, with a timeout path. `tests/scenarios/test_scenarios.py::test_s7_rep_gets_access_only_after_consent`, `tests/scenarios/test_scenarios.py::test_s8_consent_timeout_then_handoff` |
| Structured email | Preview the summary and send it to the registered mailbox through the mock Outbox. `tests/unit/test_policy_post.py::test_preview_then_send_closes`, `tests/unit/test_policy_post.py::test_other_address_restricted` |
| Graded emotional support | Empathy and alternatives precede escalation after a bounded number of attempts. `tests/scenarios/test_scenarios.py::test_s6_refused_ssn_offers_alternatives_then_human` |
| Output guard | Check pre-access leakage and grounded amounts, dates, and claim IDs. `tests/unit/test_output_guard.py::test_leak_case_id_pre_access`, `tests/unit/test_output_guard.py::test_ungrounded_amount_flagged` |
| Context-aware extraction | Prior questions and agent messages give meaning to short replies. `tests/scenarios/test_engine_core.py::test_extract_context_carries_last_agent_message` |
| Terminal phases | `HANDOFF` and `CLOSED` end the session workflow. `tests/unit/test_phases_state.py::test_terminal_has_no_exit` |
| Fixture guidance | Document eligibility, match precedence, alternatives, and fallback shape answers. `tests/scenarios/test_scenarios.py::test_s21_submission_timing_beats_processing_time`, `tests/unit/test_guidance.py::test_alternatives`, `tests/unit/test_policy_process.py::test_no_docs_case_no_data` |
| Deadline calculations | Compare claim deadlines with the configurable demo date and offer escalation after expiry. `tests/unit/test_guidance.py::test_deadline`, `tests/unit/test_policy_process.py::test_deadline_passed_directive` |

## Tests and evaluation

```sh
(cd backend && uv run pytest -q)
(cd frontend && npm test -- --run && npm run build)
make lint
```

The automated tests use scripted model doubles. Run `make eval` with a working key in `.env` to evaluate the eight conversation scripts against a live model. The runner supports `--model`, `--scenario`, and `--report` when invoked as `uv run python -m evals.run_evals` from `backend/` with credentials exported. Runs write `backend/evals/results/latest.md` (gitignored) by default; regenerate the committed report with `--report evals/results/REPORT.md`. The runner now times caller-text turns only; the committed report predates that change, so its percentiles also include deterministic consent-poll and quick-reply turns. The recorded run on `gpt-4.1-mini` passed all eight scripts with zero detected leaks, guard retries, or model errors. See the [live evaluation report](backend/evals/results/REPORT.md).

## Known limits

- Single-worker, in-memory sessions and rate limits reset when the process restarts. The demo uses fixture data and simulated email, consent, and handoff.
- Responses and fixtures are English-only. The output guard uses heuristic token checks and does not prove semantic grounding.
- There is no cap on the number of in-memory sessions, and `/api/config/validate-key` is not rate limited (demo scope).
- Custom endpoint DNS validation and the actual connection use separate resolutions, leaving a DNS rebinding window. Proxy IP handling assumes one trusted proxy that appends the client address.
