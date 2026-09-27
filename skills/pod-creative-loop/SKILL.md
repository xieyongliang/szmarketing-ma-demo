---
name: pod-creative-loop
description: Run a cloud creative loop with brief-derived acceptance criteria, independent media evaluation, consistency audit and conflict adjudication.
---

# Creative Loop

The current media connectors generate two images (design, mockup) and a 5-second 9:16 video. Acceptance criteria are dynamic, not a fixed checklist. Use the installed scripts/creative.py and its bundled evaluation.py. No local computer or external MCP is required.

## Responsibilities

The campaign includes a customer-selected boolean `watermark`. Copy it exactly into the init plan; both image and video requests use that value. If omitted, the helper defaults to true. Never use prompts to override this parameter. Resolve a conflicting brief before generating, rather than silently changing the choice. Keep this setting fixed across revisions. A requested setting is not evidence: reviewers must still inspect the actual outputs. `watermark: false` requests no optional visible generator watermark; do not promise that it removes embedded provenance or fulfills publication disclosure requirements.

You are the creator/orchestrator. Derive requirements, research, write prompts and revise. Do not grade your own output. The helper runs independent reviewer contexts against the original brief, frozen criteria and actual media. They do not receive your creation reasoning or self-assessment. These are separate model calls inside MA Cloud, not separate deployed MA Sessions. An audit always follows evaluation; adjudication runs only when the audit finds conflicts.

The helper enforces generic workflow rules: required checks must pass and the weighted score must reach the target. Omitted requirements or unresolved required conflicts prevent success. Criteria names and semantic judgments are not hard-coded.

## Workflow

Return policy: stop as soon as required checks pass and the target score is met; return that passing round. At the round limit, first select the highest-scoring round with a passed required quality gate. Only if no round has a passed gate, select the highest-scoring round overall. Keep the earlier round on a score tie. Export includes result_summary with the selected round's failed/unverified checks and score gap. Do not treat best available as approved. Never regenerate after a terminal status.

1. Research using web_search/web_fetch (at most 3 searches); record source URLs. Do not assert bestseller/trend data without sources. If research is unavailable, say so.
2. Derive criteria from the actual brief before generating. Each has a unique id, observable description, supporting source_requirement, boolean required, integer priority (1 highest, up to 100), positive weight (up to 100), and asset_refs drawn from design/mockup/video. Cover every explicit deliverable and essential requirement. Preferences may be optional; do not downgrade requirements or invent new ones.
3. Write /mnt/session/campaign-plan.json with brief, research, criteria, prompts (design/mockup/video), max_rounds (default 3, 1-5), target_score (default 4.5, 0-5), generate_audio (default false). Preserve user limits. Run python3 <skill-directory>/scripts/creative.py init --input /mnt/session/campaign-plan.json. This freezes the brief and criteria. revise changes only generation prompts, never requirements, weights or priorities.
4. Repeatedly run creative.py step with a bash timeout of at least 600 seconds. It generates assets, polls video, evaluates and audits. waiting_video, retrying_video, needs_audit and needs_adjudication mean run step again, not end the conversation. No detached processes.
5. At needs_revision, read review.priority_fix, blocking_checks and findings. Address the highest-priority issue while preserving successful requirements. Write all THREE updated prompts to /mnt/session/revised-prompts.json, run creative.py revise --input /mnt/session/revised-prompts.json, then continue step. Never supply review.json; manual review is disabled.
6. At completed, max_rounds or blocked, run creative.py export and return its exact JSON. max_rounds is not approval. blocked means the rubric omitted requirements: explain a corrected campaign is needed, do not silently rewrite the frozen contract. Only successful export is a final manifest.

## Plan Shape

Use this shape, deriving the actual criteria from the customer's brief. These are schema placeholders, not a reusable checklist:

    {
      "brief": "Original customer brief",
      "research": [],
      "criteria": [
        {"id":"deliverable_1","description":"Observable requirement","source_requirement":"Corresponding user requirement","required":true,"priority":1,"weight":1,"asset_refs":["design"]},
        {"id":"preference_1","description":"Nonessential preference","source_requirement":"Corresponding user preference","required":false,"priority":2,"weight":1,"asset_refs":["mockup","video"]}
      ],
      "prompts":{"design":"Image 1 prompt","mockup":"Image 2 prompt, using image 1 as reference","video":"Video prompt, using image 2 as reference"},
      "max_rounds":3,
      "target_score":4.5,
      "generate_audio":false,
      "watermark":true
    }

## Safety and Recovery

- Credentials come from the dedicated Environment. Never print secrets, config, headers or environment dumps. Do not call other APIs or modify helpers to bypass the workflow.
- Never modify state.json or state.sig with any tool, including Python/bash. State signatures detect accidental edits, not malicious code sharing the same key. Validation errors require correcting input or reporting a blocker, never fabricating completion.
- Each evaluation/audit/adjudication phase permits two attempts. A failed response or invalid JSON is not a passing review. Run step to retry within that bound, then stop if exhausted. These are paid model calls.
- A known transient failed Seedance task permits two replacements per quality round, reusing images with persisted backoff. GET retries query the same task. Unknown/policy errors and uncertain POSTs stop. Never retry blocked audio unchanged. retry-silent-video requires explicit authorization for a silent replacement of the specific output-audio copyright rejection.
- Video observation stops after 30 minutes. Preserve complete signed URLs; they expire. Do not claim rights clearance, supplier specifications or platform approval based on pixels. Never publish automatically.
