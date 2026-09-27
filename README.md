# SZ Creative Studio: Autonomous MA Cloud

Customer setup and reproduction: [English](CUSTOMER_DEMO_EN.md) | [中文](CUSTOMER_DEMO_ZH.md).

New campaigns execute generation, media analysis, model scoring and bounded revision inside MA Cloud. The localhost backend only creates a Session, sends the brief, observes events and renders the returned manifest. It does not call generation or evaluation APIs for cloud campaigns.

```text
Browser -> local Session bridge -> MA Cloud Session
                                  +-- main model: research and plan
                                  +-- pod-creative-loop Skill + Python
                                  |   +-- Seedream: artwork and mockup
                                  |   +-- Seedance: video and task polling
                                  |   +-- Responses SSE: independent evaluation and audit
                                  |   +-- conflict adjudication when needed
                                  +-- main model: revise from reviewed evidence
                                  +-- revise highest-priority defect, repeat
                                  +-- export best-round manifest
```

## Evaluation and iteration

MA derives acceptance criteria from the original brief before generation and freezes their requirements, priorities and weights. Independent model contexts inspect actual media, audit evidence and adjudicate conflicts when needed. The helper computes a weighted score; all required criteria must pass and the target score must be reached. Unverified required criteria prevent completion. Missing requirement coverage blocks the campaign for correction rather than silently relaxing the criteria. Otherwise MA revises up to the round limit and returns the best evaluated round. These reviewer contexts run through model API calls inside MA Cloud, not separate MA Sessions.

Defaults: maximum 3 rounds, target 4.5/5. Both are editable in the campaign form; maximum allowed rounds is 5. Each round generates one artwork, one mockup and one 5-second 9:16 video. These are helper-enforced operational bounds, not provider-enforced spending limits.

A passing round returns immediately. At the round limit, selection prioritizes the highest-scoring round that passes all required checks; if none does, it returns the highest-scoring round overall. Ties retain the earlier round. The selected result includes remaining failed/unverified checks and its score gap. Watermark is customer-configurable for both images and video.

Printing specifications, licensing and platform publication checks are separate from creative-quality scores. The model evaluates available evidence and marks unsupported items unverified. Automatic evaluation does not imply rights clearance or automatic publishing. No publishing API is connected.

## Run

Requires Node 22+, authenticated BytePlus ArkCLI, and Python 3 for helper tests/packaging.

Videos default to silent showcases (`generate_audio: false`). Seedance tasks that explicitly fail with an allowlisted temporary provider error retry at most twice per quality round, with 5/10-second backoff and persisted counters. Retries reuse generated images and do not consume quality rounds. Policy/unknown failures and expired/cancelled tasks stop for inspection. Read-only task queries retry transient network/429/5xx errors twice using the same task ID. Uncertain creation requests never auto-resubmit, avoiding duplicate paid generation. Replacement tasks may incur additional charges. Existing Sessions retain their installed Skill version; start a new Session after deploying this update.

```bash
npm ci
cp .env.example .env
# Set CLOUD_AGENT_ID, CLOUD_ENVIRONMENT_ID and ENABLE_PAID_RUNS=true.
npm start
```

Open [the workspace](http://127.0.0.1:8790). Create a campaign, set limits and click Run cloud loop once. Media and scores appear when MA returns the final manifest. A failed local observation can be resumed without sending the brief again. Temporary signed media URLs expire; JSON export is not an offline media archive.

Existing campaigns without `mode: ma_cloud` are retained and labeled Legacy local orchestration. They are not evidence of cloud autonomy. New customers should use the cloud workflow documented in the guides above.

## Deploy

1. Authenticate with `arkcli auth login`; check `arkcli auth status --format json`.
2. Package `skills/pod-creative-loop/` with its SKILL.md and scripts. Upload using `arkcli agent skill create --zip <ZIP> --display-title 'SZ Autonomous POD Loop' --format json`.
3. Create a dedicated Cloud Environment with `Type: cloud`, unrestricted networking and user-approved `Env.ARK_API_KEY`. The included `deploy-environment.mjs` reads the key from its process environment, creates a private temporary config, withholds credential-bearing output and removes the temporary file. Use an approved secret mechanism, not shared command transcripts. Change its demo resource name for another deployment.
4. Create an Agent using `cloud-system.md`, an available MA model and the returned explicit Skill ID/version. Read it back to verify tools and Skills. This account's test used seed-2-0-lite-260428; availability is account-specific.
5. Set the new Agent/Environment IDs in `.env`. Enable paid execution only with authorization.

`config.env` is NOT a secret vault: configuration readers and code in the Agent environment can access its values. This demo user explicitly approved that arrangement. Use a scoped test key, restricted access and an approved secret design before production. Never put keys into a Skill ZIP, prompt, source code or screenshot.

## Helper and recovery

The MA-resident `skills/pod-creative-loop/scripts/creative.py` uses Python's standard library. Commands: `init --input plan.json`, `step`, `revise --input prompts.json`, `status`, `export`. The Skill specifies the JSON schemas and invocation sequence. State persists at `/mnt/session/creative-loop/state.json`. Independent model calls supply scores and evidence; the helper validates their schema, computes the weighted score and enforces stop conditions. Manual reviews are disabled. Never edit state or bypass export validation.

- Image/video POSTs are not blindly retried. An uncertain outcome retains a blocking marker for inspection.
- State is HMAC-signed to detect accidental direct edits; export validates assets, evidence and scores. This is a consistency check, not a security boundary against code with access to the same environment key. The bridge also rejects observed direct write/edit calls to protected state or Skill files.
- Video polling reuses the task ID and stops after 30 minutes; it does not cancel the provider task.
- Responses SSE requires an explicit response.completed event and completed status. HTTP 200, `[DONE]`, incomplete output or a disconnect are not success. Each evaluation, audit or adjudication phase permits at most two attempts.
- The bridge correlates replies with the accepted user event and retries transient reads at most three times. Very large histories can exceed pagination/output limits.
- No external MCP or public inbound endpoint is needed. The sandbox makes outbound model/research calls.
- The UI is localhost-only, without production authentication or multi-tenant isolation.
- Public-source research is not verified competitor sales analytics or a real-time trend connector. UGC-style material must not pretend to be real customer testimony.

## Verify

```bash
npm test
python3 test-cloud.py
```

The September 26, 2026 cloud test passed in round 1 with a model-reported score of 5/5, four required checks passing, and no audit conflicts. It used three maximum rounds, a 4.5 target, and watermark disabled. Later-round selection and adjudication were not exercised by this run. The exported research list was empty; market research is not demonstrated by this result. Model acceptance is not human inspection or publishing approval. See the customer guides for the complete verification boundaries.

Local regression coverage includes 26 Node.js tests and 29 Python tests. These tests use mocks rather than paid model calls.

## Security and distribution

Private credentials, generated assets, signed URLs, and historical internal test notes are excluded from Git. Use your own resources and dedicated test key. Never commit `.env`, `data/`, authentication caches, or complete Environment configurations. Campaign exports may contain private briefs and signed media URLs; redact them before sharing. This repository is a demo, not a production security or compliance solution.
