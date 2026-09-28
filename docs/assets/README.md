# Documentation Asset Inventory

## September 28 Cloud Retest

The run used Agent / Skill v9. Round 1 scored 3.333333/5 and failed the required-item gate. After prompt revision, round 2 scored 5/5 and passed all eight required checks. No third round was generated.

| Files | Source / role |
| --- | --- |
| `retest-20260928/round-1-design.jpg`, `round-2-design.jpg` | Original Seedream output; also the reference for the matching round's mockup |
| `retest-20260928/round-1-mockup.jpg`, `round-2-mockup.jpg` | Original Seedream output; also the reference for the matching round's video |
| `retest-20260928/round-1-video.mp4`, `round-2-video.mp4` | Original Seedance output |
| `retest-20260928/round-2-video-poster.jpg` | First frame extracted from the selected video; not a separately generated image |
| `retest-20260928/result.json` | Sanitized run export with prompts, criteria, reports, file sizes, and SHA-256 checksums |
| `ui-workspace.png`, `ui-review.png`, `ui-design.png`, `ui-video.png` | Actual frontend screenshots of the September 28 run |
| `ui-campaign-setup.png` | Actual form filled with reproduction settings, not submitted for the screenshot |
| `ui-reference-mug.jpg` | Decorative Unsplash photograph referenced in `public/index.html`; not used as generation input |

Both videos were independently probed: 720x1280, 5.041667 seconds, no audio stream. Scores are model judgments, not printing, rights, or publication approval. The run contains no verified research references (`research=[]`).

Reference photograph: [Unsplash source](https://images.unsplash.com/photo-1514228742587-6b1558fcca3d?w=1000&auto=format&fit=crop&q=85). Rights remain with the respective rights holder; confirm applicable permissions before redistribution.

The separate `v9/evaluation.json` is a historical sanitized September 26 report. Its original media expired and is not included. Do not confuse that report with the September 28 media and scores.

Do not add raw Campaign JSON, credentials, Session IDs, or signed URLs here. Reviewed customer briefs and evaluation text still need appropriate sharing permission.
