# PRD: Voice AI Assistant Web Application Template

**Type:** new project / template
**State:** decomposed into `.scratch/voice-ai-template/issues/`

## Problem Statement

Developers building voice AI assistant web applications repeatedly solve the same setup problems before they can write any product-specific code. Each new project re-decides the realtime audio stack, the auth provider, the database, the memory layer, the monorepo tooling, the linting and formatting setup, the test scaffolding, the docker layout, and the deployment shape. The decisions are non-trivial — voice AI specifically is unfamiliar to many developers, and getting low-latency speech working with cross-session memory and tool calls is genuinely hard to assemble from scratch.

The result is that early days of a new project are spent on infrastructure rather than product, and projects that "look the same" diverge in their wiring such that knowledge does not transfer between teams.

## Solution

A monorepo template that ships a working voice AI assistant out of the box, with industry-recommended defaults for every layer, clear separation between domain logic and adapters, and a runnable demo that exercises every moving part the moment it is cloned.

When a developer clones the template, installs dependencies, and starts the dev stack, they should be able to sign in, click a microphone, talk to an assistant that responds in real time with sub-second time-to-first-audio, have it remember their stated preferences across sessions, recall things they previously mentioned, and call a real external API as a tool — all without registering for any third-party service that requires a credit card.

The template provides a foundation that the developer extends by adding domain-specific tools, pages, and prompts; it does not provide a finished product.

## User Stories

### Developer cloning and running the template

1. As a developer cloning the template, I want a documented set of prerequisites and a single setup command, so that I can reach a working dev environment without piecing together instructions from multiple sources.
2. As a developer, I want a single command to start the entire dev stack, so that I can talk to the assistant within minutes of cloning.
3. As a developer, I want pre-commit hooks installed automatically, so that I cannot accidentally commit unformatted, unlinted, or secrets-bearing code.
4. As a developer, I want my commit messages validated against conventional-commit format, so that the git history stays readable and downstream automation remains possible.
5. As a developer, I want type-safe HTTP calls from the frontend to the backend, so that schema drift is a compile-time error rather than a runtime surprise.
6. As a developer, I want the agent and the API to share business logic via a single Python package, so that I write each rule once and both surfaces stay consistent.
7. As a developer, I want secrets to never be committed, with a baseline scanner that blocks new secrets from being added, so that the template stays safe to fork publicly.
8. As a developer, I want a clear `.env.example` that documents every variable the system needs, so that I know exactly what to configure before running.

### Developer extending the template

9. As a developer adding a new domain tool, I want the tool registration pattern to be obvious and copy-pasteable, so that I extend the assistant without studying the framework internals.
10. As a developer adding a new database table, I want migrations managed by a single tool, so that schema changes are versioned consistently across local and production.
11. As a developer, I want row-level security enforced at the database, so that user data isolation does not depend on remembering to filter in every application code path.
12. As a developer, I want example tests for each module type, so that I have a pattern to copy when adding new tests.
13. As a developer, I want the agent's tool-calling logic testable without WebRTC or live LLM calls, so that I can iterate on prompts and tools quickly and run the suite in CI.
14. As a developer, I want integration tests that run against a real Postgres, so that query-level bugs are caught before they reach production.
15. As a developer extending the realtime model, I want the model provider swappable via configuration, so that I am not locked into a single vendor.
16. As a developer, I want the system prompt and agent instructions in version-controlled files, so that prompt changes show up in code review.
17. As a developer, I want a clear separation between the API and the agent worker, so that one cannot accidentally couple to the other beyond the shared package.
18. As a developer, I want the example external-API tool to call a real, key-less API, so that I can see the full async-tool pattern working without registration friction.
19. As a developer, I want the example tool to demonstrate timeouts and graceful failure, so that I know the expected pattern for production tools.

### Developer deploying

20. As a developer, I want a Dockerfile per service, so that each component can be deployed and scaled independently.
21. As a developer, I want a development docker-compose and a production docker-compose, so that I can self-host the entire stack when privacy or cost requires it.
22. As a developer, I want documented deployment targets per service, so that I know which platforms suit the long-running agent worker versus the stateless API versus the static web bundle.
23. As a developer, I want CI to run on every pull request, so that lint, type, and test failures are caught before merge.
24. As a developer, I want to swap from hosted realtime infrastructure to a self-hosted equivalent by changing environment variables, so that I am not locked into a hosted provider once I move to production.

### End user of an application built from the template

25. As an end user, I want to sign in to the assistant, so that my conversations and preferences are tied to me across sessions and devices.
26. As an end user, I want to talk to the assistant by clicking a microphone button, so that I can interact naturally without typing.
27. As an end user, I want the assistant to respond aloud quickly enough that the conversation does not feel transactional, so that the experience feels like a conversation rather than a query interface.
28. As an end user, I want the assistant to remember preferences I state during conversation, so that I do not have to repeat them.
29. As an end user, I want the assistant to recall things I mentioned in previous conversations, so that the relationship feels continuous rather than amnesiac.
30. As an end user, I want the assistant to look up real information when I ask, so that it is more useful than a closed chat partner.
31. As an end user, I want to interrupt the assistant when it is speaking, so that the conversation feels natural rather than turn-locked.
32. As an end user, I want to see a live transcript of the current conversation, so that I can verify what was heard and what was said.
33. As an end user, I want to see a list of my past conversations, so that I can revisit what was discussed.
34. As an end user, I want to view the transcript of any past conversation, so that I can find specific information later.
35. As an end user, I want to change my preferred voice, so that the assistant matches my taste.
36. As an end user, I want to sign out, so that my session ends cleanly on shared devices.
37. As an end user, I want to see what the assistant has remembered about me, so that I can verify and trust what is being stored.
38. As an end user, I want my data isolated from other users at the database level, so that I trust the system with personal information.
39. As an end user, I want the assistant to acknowledge when a tool call fails, so that I am not left wondering whether my request worked.

### Operator running an application built from the template

40. As an operator, I want services to log structured JSON to stdout, so that any log aggregator can ingest them without custom parsers.
41. As an operator, I want every request and conversation to carry a correlation identifier in its log lines, so that I can trace a single interaction across services.
42. As an operator, I want the agent worker to scale horizontally by adding more containers, so that concurrent conversation capacity grows linearly with infrastructure.
43. As an operator, I want server-side time-to-first-audio logged per turn, so that latency regressions are visible in logs even before a dashboard is in place.
44. As an operator, I want database migrations applied through a single deterministic command, so that production schema changes are predictable.

## Implementation Decisions

### Voice and realtime stack

- The voice loop is **real-time conversational** (full-duplex WebRTC), not turn-based recording. The framework is **LiveKit Agents** in Python, defaulting to a speech-to-speech model as the realtime engine. The default model is **OpenAI Realtime**; the seam is a configurable model factory so a downstream project can swap to any other realtime provider or to a classic STT-LLM-TTS pipeline without changing call sites.
- The agent is a **tool-using single agent**, not multi-agent or workflow-orchestrated. Multi-agent and RAG-over-documents are explicitly out of scope.
- LiveKit's media plane runs on **LiveKit Cloud for development** (zero-setup, free tier sufficient for dev) and on a **self-hosted LiveKit server in the production compose** (one container, one config file). Application code is unchanged between the two — only environment variables differ.

### Identity, database, and memory

- **Supabase** provides authentication, Postgres, and pgvector in one stack. This choice is driven by self-hostability via Docker, the alignment of row-level security with user-scoped queries, and the avoidance of vendor lock-in for memory storage.
- **Postgres with pgvector** is the only data store. There is no separate vector database. The same instance hosts auth tables, application tables, and the memory layer's vector tables.
- Memory is **hybrid**:
  - **Structured user preferences** live in a typed table keyed by `(user_id, key)`. The agent has explicit get/set tools for them. This table handles deterministic facts such as a stated favorite color.
  - **Episodic and semantic memory** is delegated to **mem0** with its pgvector backend pointed at the same Postgres. The agent has explicit `remember` and `recall` tools. Mem0 owns deduplication, conflict resolution on updated facts, and similarity search.
- **Conversation transcripts are persisted** as a `conversations` and `messages` pair. Audio recordings are not persisted in the default template.
- **Row-level security** policies protect every user-scoped table. Application code does not enforce filtering — the database does.

### Monorepo shape and shared logic

- The monorepo follows a strict **shared-core pattern**. Domain logic, schema, and the memory layer live in a Python package shared by both the API and the agent. Each app is a thin adapter — the API translates HTTP into core calls, the agent translates LiveKit room events into core calls. Neither app contains business logic that is not also exposed as a `core` function.
- **Major modules in `core` are deep**: each presents a small, stable interface and hides substantial complexity. The list:
  - `core.auth` — verifies Supabase JWTs and produces the resolved current user.
  - `core.preferences` — set/get structured preferences.
  - `core.memory` — `remember` and `recall` over mem0.
  - `core.conversations` — start, append message, end with optional summary.
  - `core.tools` — decorator-based tool registration plus dispatch with built-in instrumentation and error mapping.
  - `core.observability` — structured logging setup and the LiveKit metrics-event handler.
  - `core.config` — typed settings loaded from environment variables.
- Adapters (the three apps) are deliberately shallow. Adding a new entrypoint such as a CLI or a telephony bridge means a new adapter, not a new core module.

### Frontend

- **Vite + React SPA**, with **TanStack Router** for file-based routing. No SSR. The choice is driven by the fact that the app is fully authenticated and SEO-irrelevant, and by the cleaner separation that comes from having only one backend (the Python API) rather than competing with Next-style server features.
- **shadcn/ui + Tailwind** as the UI layer. Components are owned by the repo rather than imported from a versioned library, which suits the customization expected of a template.
- **TanStack Query** for HTTP state, **React Hook Form + Zod** for forms, **`@livekit/components-react`** for room and track hooks, **Supabase JS** for auth. No global state library is included by default; if needed in future, Zustand is the chosen escape hatch.
- The frontend ships **five routes**: sign-in, the main talk page, conversation history, a single-conversation transcript viewer, and a settings page. The talk page includes a "what I remember about you" sidebar that reads from preferences and memory, so the developer cloning the template can see memory working visibly.
- TypeScript types for the API are generated from the API's OpenAPI schema as a build step; they live inside the web app rather than in a shared package, since there is no second TypeScript consumer.

### Tooling, formatting, and linting

- **uv workspaces** for Python dependency management and shared-package linking.
- **pnpm workspaces** for TypeScript dependency management.
- **Turborepo** as the cross-language task runner with caching for TypeScript pipelines.
- **Ruff** (formatter and linter) and **mypy** (type checker) for Python. **Prettier**, **ESLint** (flat config), and **tsc --noEmit** for TypeScript.
- **Pre-commit framework** as the hook runner. Hooks are split into two tiers: fast hooks on commit (formatters, linters, secret scan, hygiene checks, conventional-commit validation) and slower hooks on push (type checkers, fast unit tests).
- **Conventional commits enforced via commitlint** at commit-msg stage from the first commit.

### Persistence, migrations, and configuration

- **Supabase CLI** owns migrations. SQL files are committed and applied identically in dev and production. No ORM-level migration tool is added on top.
- **`.env.example`** is the canonical reference for required variables. Local `.env` files are gitignored.
- **`detect-secrets`** baseline blocks accidental secret commits.
- No secrets manager (Vault, Doppler, Infisical) is baked in; the seam is a typed settings module that reads the environment.

### Observability and logging

- **Structured logging** via `structlog`, JSON output in production. Per-request and per-conversation correlation IDs are bound into the logger context by middleware.
- **LiveKit Agents emits per-turn metrics** including end-of-utterance delay, time-to-first-token, time-to-first-audio-byte, and total latency. These events are logged as structured JSON lines from the agent worker. No dashboard, tracing backend, or APM is included in the default template.
- A heavier observability stack (Langfuse, Prometheus/Grafana, OpenTelemetry collectors) is explicitly deferred to a future iteration.

### Deployment

- A **Dockerfile per service** (web, api, agent), each multi-stage, each running as a non-root user.
- **Two compose files**: a development compose targeting hosted realtime/auth where appropriate, and a production compose that adds the self-hosted realtime server and otherwise pins everything self-hostable.
- **No vendor-specific deployment manifests** are committed. The README documents which platforms suit which service, with explicit notes that the agent worker requires a long-running container runtime and is not compatible with cold-start serverless platforms.
- **CI on GitHub Actions**: three parallel jobs covering lint, test (including integration with an ephemeral Postgres), and a docker-build sanity check. No deploy step is included.

### Demo behavior

- Out of the box, the agent ships with two example domain tools beyond the memory tools: a trivial `get_current_time` and a `get_weather(city)` tool that calls **Open-Meteo** with no API key. The weather tool performs two HTTP calls (geocoding then forecast), uses async HTTP with explicit timeouts, and returns a graceful message when the city cannot be found. This serves as the canonical pattern for downstream developers adding their own tools.
- The system prompt instructs the agent to use memory tools naturally — saving stated preferences, recalling relevant facts before answering personal questions.

## Testing Decisions

### What makes a good test

- A good test exercises **external behavior** of a module — its public interface and observable effects — not its internal implementation. This keeps tests stable across refactors of the module's internals.
- Tests are **deterministic**: integration tests use ephemeral test containers; agent-loop tests mock the realtime model with scripted responses; tool tests mock external HTTP at the transport layer.
- Tests are **fast in the inner loop**: unit tests run on push via the pre-commit framework; the slower integration suite runs in CI.
- The test suite does **not attempt to evaluate the quality of LLM responses**. That is an evals concern, distinct from testing, and is out of scope.

### Modules under test

- **`core.auth`** — unit tests covering valid tokens, expired tokens, malformed tokens, and missing claims.
- **`core.preferences`** — unit tests against the module surface and integration tests against a real Postgres exercising row-level security.
- **`core.memory`** — unit tests with a mocked mem0 client and **integration tests against a real mem0 instance backed by a real Postgres**, covering remember, recall, fact updates, and conflict resolution.
- **`core.conversations`** — unit tests and integration tests against a real Postgres covering ordering, append, end-of-conversation summaries.
- **`core.tools`** — unit tests for the dispatcher and the example tools, with the weather tool's external HTTP mocked at the transport layer to assert timeout and failure behavior.
- **API route handlers** — unit tests with mocked core dependencies, asserting status codes, error mapping, and authorization gating.
- **Agent session** — an integration-style test using LiveKit Agents' built-in session test harness with a mocked realtime model, asserting that a scripted user turn produces the expected tool calls and message persistence.
- **Frontend** — example unit tests for one component and one hook using vitest and React Testing Library, establishing the pattern.

End-to-end browser tests via Playwright are explicitly deferred.

### Prior art

This is a greenfield repository, so no prior tests exist within the project. The example tests shipped in the template **become** the prior art for downstream developers. They are written deliberately as patterns to copy, with one well-commented example per type.

## Out of Scope

- Audio recording and replay of conversations. Only text transcripts are persisted.
- Heavy observability infrastructure: Langfuse, Prometheus, Grafana, OpenTelemetry collectors, dashboards.
- End-to-end browser tests via Playwright.
- Snapshot tests and CI coverage thresholds.
- Helm charts, Kubernetes manifests, Terraform, Pulumi, or any infrastructure-as-code beyond Dockerfiles and compose files.
- Pre-baked deployment workflow steps in CI; only stub workflow files for downstream completion.
- Multi-tenancy and organization/team structures.
- Enterprise SSO, B2B authentication, SAML.
- Mobile applications and PWA support.
- Internationalization and localization.
- Phone and telephony integration (SIP, Twilio).
- Multi-agent orchestration, agent handoffs.
- Retrieval-augmented generation over user documents.
- Frontend error tracking integrations (Sentry hookup is left as a documented seam).
- Auto-versioning, changesets, release-please, or any release-management tooling beyond the conventional-commit format itself.
- A separate shared-types TypeScript package; types are generated into the web app until a second TypeScript consumer exists.

## Further Notes

- The template intentionally favors hosted infrastructure for development (LiveKit Cloud, Supabase Cloud are valid choices) and self-hosted infrastructure for production (the production compose runs everything in containers). Both shapes are exercised by the same application code; the difference is environment variables. This dual posture is the central design tension and is justified by the need for minute-zero developer velocity without surrendering long-term self-hostability.
- The "what I remember about you" sidebar in the demo UI is small in code but high in signal: it makes memory visibly present from the first interaction, which prevents the common template-clone failure mode of "is the memory layer working or not?"
- Future iterations are expected to add: a real observability stack (Langfuse first), client-side time-to-first-audio capture, end-to-end tests for the voice loop, telephony integration, mobile clients, and an evals harness for response quality.
- Implementation issues split out from this PRD live alongside it under `.scratch/voice-ai-template/issues/`, numbered and named per the local issue-tracker convention.
