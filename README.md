# AI Visibility Intelligence API

A Flask REST API that runs a three-agent AI pipeline to discover the questions
people ask AI assistants in a business's competitive space, score how visible
the business currently is in those AI-generated answers, and generate content
recommendations to close the visibility gaps.

## Setup

### Option A — Docker (recommended, uses Postgres)

```bash
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY (or OPENAI_API_KEY + AI_PROVIDER=openai)
docker-compose up --build
```

The API is then available at `http://localhost:5000`.

### Option B — Local, no Docker (SQLite)

```bash
./setup.sh                 # creates venv, installs deps, runs migrations
source venv/bin/activate
export FLASK_APP=run.py
flask run
```

### Running without any LLM API key

The app is intentionally runnable cold: with no `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` set, every agent falls back to a deterministic
template-based result (see "Fallback behaviour" below) rather than crashing.
This is useful for smoke-testing the API surface, but you'll want real keys
to see the actual multi-agent reasoning.

### Running tests

```bash
pip install -r requirements.txt
pytest -v
```

Tests mock the LLM client entirely (`app.services.llm_client.LLMClient.complete_json`)
so they run in milliseconds with no network calls or API costs, covering
happy paths, malformed-output handling, and the opportunity score formula.

## Architecture

```
app/
├── __init__.py          # create_app() factory
├── extensions.py        # db, migrate, limiter singletons (avoids circular imports)
├── models/               # BusinessProfile, PipelineRun, DiscoveredQuery, ContentRecommendation
├── agents/
│   ├── base.py           # shared LLM-calling + fallback contract
│   ├── discovery.py       # Agent 1
│   ├── scoring.py         # Agent 2
│   └── recommendation.py  # Agent 3
├── services/
│   ├── llm_client.py      # provider-agnostic JSON-mode LLM wrapper
│   ├── external_data.py   # DataForSEO client + labelled simulated fallback
│   └── pipeline.py        # orchestrator: Agent 1 → Agent 2 → Agent 3
├── api/
│   ├── profiles.py        # POST/GET profiles, POST .../run
│   └── queries.py         # GET queries, GET recommendations, POST recheck
└── utils/
    ├── scoring.py          # opportunity score formula
    └── errors.py           # APIError hierarchy → consistent JSON error shape
```

**App factory pattern**: `create_app(config_name)` builds and configures the
Flask app so tests can spin up an isolated in-memory-SQLite instance
(`config_name="testing"`) independent of the dev/prod app.

**Why `extensions.py` is separate from `__init__.py`**: models, agents, and
blueprints all need `db`, and importing it from `app/__init__.py` directly
would create circular imports the moment any of those modules is imported
before `create_app()` runs.

### Why Anthropic (Claude) as the default provider

`AI_PROVIDER` is configurable (`anthropic` or `openai`); I defaulted to
Anthropic because:
- The recommendation/discovery agents need to hit a strict JSON schema
  reliably — Claude models follow structured-output system prompts well
  without needing a dedicated JSON mode.
- All three agents are single-turn, moderate-context classification/generation
  tasks (not agentic tool use), so a mid-tier model is sufficient — cost and
  latency matter more than raw capability here, given the pipeline fires
  ~20+ LLM calls per run (1 discovery call + up to 20 scoring calls + 1
  recommendation call).
- The `LLMClient` wrapper (`app/services/llm_client.py`) keeps both providers
  behind one interface, so switching is a one-line config change — useful if
  you want to A/B different models per agent (e.g. a cheaper model for the
  20x-called scoring agent, a stronger one for discovery/recommendations).

### Agent separation & failure isolation

Each agent is an independent class with its own system prompt, its own
input validation, and its own fallback — none of them share mutable state,
and each can be unit tested in isolation by mocking `LLMClient.complete_json`
(see `tests/test_agents.py`).

The orchestrator (`PipelineOrchestrator.run`) implements the partial-failure
policy the spec calls for:
- **Agent 1 fails entirely** → the whole run is marked `failed` (nothing to
  score or recommend without queries), but the deterministic template
  fallback in `QueryDiscoveryAgent._fallback` usually prevents this — it only
  triggers if *both* the LLM call and its retry fail.
- **Agent 2 fails for one query** → that single query is still persisted
  with a conservative "not visible" default and an explanatory note; scoring
  continues for the rest of the batch. The run is marked `partial_failure`
  rather than `failed` if this happens.
- **Agent 3 fails** → queries were still discovered and scored and are
  fully queryable; the run is marked `partial_failure` and
  `content_recommendations` comes back empty (or from its own template
  fallback, covering the top gap queries).

### Fallback behaviour

Every agent has a non-LLM fallback path (see `_fallback` methods in
`discovery.py` and `recommendation.py`) so a provider outage or malformed
response never crashes the pipeline — it degrades to template-based output
and reports the degradation via `PipelineRun.agent_status` and
`error_message`.

## Opportunity Score Formula

Documented in full in `app/utils/scoring.py`; summarized here:

```
opportunity_score = 0.35 * volume_factor
                   + 0.20 * ease_factor
                   + 0.30 * gap_factor
                   + 0.15 * intent_factor
```

| Factor | Weight | What it measures | Why this weight |
|---|---|---|---|
| `volume_factor` | 0.35 | `log1p(search_volume) / log1p(10000)`, capped at 1.0 | Log-scaled because raw search volume is extremely right-skewed; without log-scaling, a handful of head terms would dominate every ranking. |
| `ease_factor` | 0.20 | `(100 - competitive_difficulty) / 100` | Easier queries are more realistically winnable soon, but weighted less than volume/gap since a very easy, very low-value query still isn't a great opportunity. |
| `gap_factor` | 0.30 | `1.0` if not currently visible, `0.15` if already visible | Closing visibility gaps is the platform's core value proposition, so this is weighted second-highest. Already-visible queries keep a small residual score (defending/reinforcing has some value) rather than dropping to zero. |
| `intent_factor` | 0.15 | Lookup by Agent 1's intent classification (`comparison`=1.0, `best_of`=0.9, `transactional`=0.85, `informational`=0.5) | Comparison/best-of queries correlate with users closer to a purchase decision. |

All four sub-factors are pre-normalized to `[0, 1]` and the weights sum to
`1.0`, so the result is naturally bounded without needing a final clamp
(a clamp is applied anyway as a defensive guard).

## Data model decisions

- **UUID primary keys** (`app/models/base.py::UUIDMixin`) instead of
  auto-increment integers, since the API spec exposes UUIDs directly in
  every response and I didn't want to leak or rely on sequential DB IDs.
- **`PipelineRun` is a first-class table**, not just a side effect of
  triggering `/run`, so that `DiscoveredQuery` and `ContentRecommendation`
  rows can be traced back to exactly which run produced them (`run_uuid` FK
  on both) — this is what makes `/recheck` meaningfully different from a
  fresh pipeline run: it updates a query in place without creating a new
  `PipelineRun`.
- **`competitors` and `target_keywords` are stored as native JSON columns**
  rather than a separate many-to-many table, since they're small,
  order-sensitive lists that are always read/written as a unit with their
  parent row — normalizing them would add joins for no query benefit at this
  scale.
- **`agent_status` JSON column on `PipelineRun`** records per-agent
  ok/fallback/partial status without a separate table, since it's only ever
  read alongside its parent run, not queried independently.

## External data (DataForSEO)

`app/services/external_data.py` calls DataForSEO's `search_volume/live`
endpoint when `DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD` are set and
`USE_MOCK_EXTERNAL_DATA=false`. Without those credentials (the default), it
falls back to a **deterministic, clearly-labelled simulated estimator**
(`source: "simulated"` in the recheck response) so the API is runnable
end-to-end without a paid trial. Every `DiscoveredQuery.visibility_notes` /
recheck response is honest about which mode produced the numbers — this is
called out explicitly rather than silently passed off as real data, per the
assessment's requirement to use real third-party data where available.

## Endpoints implemented

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/profiles` | Register a business profile |
| GET | `/api/v1/profiles/{uuid}` | Get profile + summary stats |
| POST | `/api/v1/profiles/{uuid}/run` | Run the full 3-agent pipeline |
| GET | `/api/v1/profiles/{uuid}/queries` | List queries (filters: `min_score`, `status`, `page`, `per_page`) |
| GET | `/api/v1/profiles/{uuid}/recommendations` | List content recommendations |
| POST | `/api/v1/queries/{uuid}/recheck` | Re-run Agent 2 on a single query |
| GET | `/health` | Liveness check |

All error responses share one shape:

```json
{"error": {"code": "validation_error", "message": "...", "details": null}}
```

## Tradeoffs / what I'd do differently with more time

- **Synchronous pipeline execution**: per the spec, this is acceptable, but a
  20-query run means ~22 sequential LLM calls. I kept scoring calls
  sequential for simplicity and clearer failure isolation per-query; a real
  next step is to parallelize Agent 2 calls (e.g. `concurrent.futures`) since
  they're independent of each other.
- **Rate limiting** (`Flask-Limiter`, bonus item) is applied only to
  `POST /run` since it's the expensive, LLM-calling endpoint; it's an
  optional dependency — the app runs fine without it installed, just
  unrated.
- **Async execution with a status-polling endpoint** was not implemented
  (noted as a bonus in the spec) — `/run` is currently a single blocking
  request. Given more time, I'd move it to a Celery task with a
  `GET /profiles/{uuid}/runs/{run_uuid}` polling endpoint.
- **`visibility_position` is not currently exposed as a filterable query
  param** (only `status`), since the spec's filter list didn't call for it —
  easy to add if needed.
- **Migrations**: `flask-migrate`/Alembic is wired up (`app/extensions.py`,
  `setup.sh` runs `flask db migrate/upgrade`); I did not commit a pre-generated
  `migrations/` folder since it's environment-specific — `setup.sh` and the
  Docker Compose `api` service both generate/apply it on first run.

## AI tools used

This implementation (agent prompts, orchestration logic, Flask API, tests,
and this README) was built with Claude as a coding assistant.
