# ATLAS Amendment 001: any model, any backend, $0 to build

Decided by Dippo, 2026-10-12. Supersedes the parts of PLAN.md and DECISIONS.md listed below. Everything not listed stays as written (TypeScript stack, proxy-first logging, deterministic grading, tamper check, STATUS-line claims, taxonomy, task rules, CLAUDE.md working rules).

## Why

ATLAS stalled at G0 because the plan was built around one paid API run. ATLAS is now a reusable benchmark that can test anything against anything: API models, local models, and subscription agents. The first consumer is ROCm Recipes 006 (Qwen3.8-27B on a local MI300X endpoint, concurrency 1/4/8/16). Example comparisons it must support later: a 4B local Gemma vs Claude Opus 5.5 API; Codex subscription vs Claude API.

## Money rule (overrides D18-D20, D24, D25)

- **API spend approved: $0.** No command may call a paid API until Dippo approves a specific budget in DECISIONS.md.
- All development and smoke testing uses a free local model on the Mac Studio (an MLX OpenAI-compatible server, `mlx_lm.server`, reached from containers via `host.docker.internal`).
- Per-run and total USD caps stay in the code and apply to the `api` backend. They're set per campaign, not globally.

## A1. Run config replaces the single global model (overrides D1, D16, D17)

A run is defined by a **run config**, not by global settings:

```
{ id, harness, backend, model, effort | null, label }
```

Configs live in `config/run-configs/*.ts` (or `.json`). Manifests reference config ids. `run_id` becomes `<task>__<config>__a<n>`. The `runs` table gets `config_id`, `backend`, `model`, `token_source`, and `cost_basis` columns.

## A2. Three backends

| Backend | Examples | Model traffic | Tokens | Cost basis |
|---|---|---|---|---|
| `api` | Claude API, OpenAI API, OpenRouter | through the proxy | proxy (exact) | tokens × dated list price (D14) |
| `local` | vLLM/SGLang on MI300X, MLX on Mac | through the proxy, upstream = OpenAI-compatible URL | proxy (exact) | GPU-hours × hourly rate, set per campaign (e.g. $1.99/hr MI300X); $0 for owned hardware, with that stated |
| `subscription` | Codex CLI on a ChatGPT plan, Claude Code on a Claude plan | **not** through the proxy (the vendor's own client and login) | the client's own usage output if it has one, otherwise `unavailable` | `subscription`: report plan name and price, marginal cost $0, plus a rate-limit note |

Rules:
- `token_source` is `proxy | self_report | unavailable`. Results never mix sources in one number without saying so.
- A `subscription` run is a **system** result (model + vendor harness + vendor settings), not a model result. Exports and the site must label it that way.
- Effort for `subscription` is whatever the client's own flag sets, recorded as requested, with `effort_enforced = null`.
- Network isolation still applies. A `subscription` container may reach only that vendor's API hosts (allowlist per adapter), and its login credential is mounted read-only per run, never baked into an image or committed. If isolation can't be done cleanly for one, stop and report it under "Waiting on Dippo".
- Check each vendor's current terms for scripted or automated use before building its adapter, and record the URL in DECISIONS.md. If the terms are unclear, mark it under "Waiting on Dippo" and skip that adapter.

## A3. Harnesses

- **First harness: OpenCode** (viable per docs/harness-matrix.md, works with any OpenAI-compatible or Anthropic URL). It covers `api` and `local`, and it's the harness 006 uses.
- **Subscription adapters:** `codex` (Codex CLI, `codex exec`) and `claude-code` (`claude -p`). Check current docs for the exact flags. Build them after the OpenCode path passes end to end. They don't block 006.
- Hermes, OpenHands, OpenHuman, and the harness-comparison study move to BACKLOG.md as a future ATLAS release. Their matrix research stays.

## A4. Tasks (overrides D1 task count)

- **30 tasks**, still mined from Dippo's own repos under the existing task rules.
- P3.2 mines about 45 candidates. G1 picks 34 to 36 (buffer for validation failures).
- Freeze tag stays `tasks-v1`.
- Docker images must build for both `linux/arm64` (Mac Studio) and `linux/amd64` (MI300X host).

## A5. Concurrency

The orchestrator must support concurrency up to 32 with a continuous queue: a new run starts as soon as a slot frees. Per run, record `inference_s` (time waiting on model responses, from the proxy) separately from total `wall_s`.

## A6. G0 resolved

| Item | Value |
|---|---|
| D16 model | No global model. Set per run config (A1). |
| D17 harnesses | OpenCode first, then the codex and claude-code subscription adapters (A3) |
| D18 per-run cap | Per campaign, `api` backend only |
| D19 total cap | Per campaign. Currently $0 approved. |
| D20 dev budget | $0 (local model only) |
| D21 timeout | 30 min default, overridable per campaign |
| D22 machine | Mac Studio for build and dev, concurrency 3. 006 runs on the MI300X host. |
| D23 proxy | LiteLLM, exact pinned version |
| D24 pilot | Dropped as a gate. Each campaign gets its own small smoke run on its own backend. |

## A7. Phase changes

- **Phase 1:** P1.3 uses the local MLX model. P1.4 = OpenCode on `api` + `local` config types (`api` verified with the proxy's mock or a cap of $0 that must trigger), then the codex and claude-code adapters.
- **Phase 3:** as amended in A4.
- **Phases 4-8:** replaced by **campaigns**. A campaign is a manifest plus run configs plus its own budget, smoke run, analysis, and export. Campaign 1 is ROCm Recipes 006, run from the 006 study plan. The existing Phase 4-8 steps become the template for any campaign that compares configs.
- Stop after Phase 3 (tasks frozen) and wait for Dippo.

## A8. ATLAS v1.1 grader and interrupted-request accounting (dippo, 2026-10-19)

Authorized by the 006 post-final correction request, for 007 and future campaigns. The tasks-v1 tag, task sources, hidden tests, frozen dependency recipes, taxonomy, tamper rules and official 006 exports stay unchanged.

**Grader v1.1.** Workspace snapshots exclude entries named `node_modules` at every depth before lstat/copy/hash. Dependencies come from the frozen native dependency image and preparation recipe. Other symlinks/special files and symlink roots remain rejected. This is a workspace-only policy: task/hidden-test hashing stays closed and unchanged. Both pre-test and post-test workspace hashes use the same policy. New test/grade records and persistent fingerprints include `graderVersion: "1.1"`. Old cached grades are not silently reused/relabelled; a changed fingerprint still requires a separate regrade decision/new campaign store. Protected-path tamper checks remain decisive.

**Proxy usage.** A downstream disconnect no longer immediately aborts an already dispatched request. The proxy stops delivery and drains that one upstream call for up to 30 seconds, retaining final usage before owned teardown. Container/supervisor cleanup drains first; the control endpoint is loopback-only and admits no new inference. No request is retried. On errors or grace expiry, observed usage is still logged: validated terminal usage is exact; nonterminal counts are `reported_partial` with `token_source=unavailable` and conservative API reservation retained. Missing components stay null, never inferred. Undelivered post-cutoff text cannot become a final completion claim. Providers that never report usage, forced SIGKILL and grace expiry without final usage can still leave totals unavailable. The proxy image gets a new v4 tag; 006's v3 is not overwritten.

**006 versus 007.** Official 006 remains at `279889b8f42c607344781766503602a8c462f5df` (v1.0 grading). Its separate saved-diff sensitivity regrades 13 snapshot-infra attempts on evooffice amd64 with freshly rebuilt frozen recipes and unchanged hidden tests. Four recovered test passes retain original tamper=true; none adds a strict solve. Regraded originals replace their retries: c16/c8/c4 become 3/30, 7/30, 6/30, versus official 3/29, 7/29, 6/29. Saved-diff reconstruction also omits untracked generated files: C10 retry-1's `.tmp-verify/work/dangle.txt` would still be rejected by full-workspace v1.1 grading. This panel is not a blanket v1.1 replay of every original workspace.

007 must label grader version independently of task-set identity. Turning an infra exclusion into a verdict changes denominators and possibly scores; it is not evidence of model improvement. Compare a common grading policy or display official and sensitivity panels separately, preserving cap/tamper precedence. Draining can include engine work after agent cutoff, so distinguish agent wall/caps from provider usage and teardown grace. 006 sampler deltas recover complete engine-side prompt/cache input totals for c16/c8/c4, not complete output or per-request allocation. Do not substitute engine input for missing output or claim complete exact token-cost comparability. The 006 `results/analysis/` files and handoff retain sources, coverage and statistics.
