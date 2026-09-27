"""MA-resident media operations with independent, evidence-based model reviews."""
import argparse
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
import evaluation as ev

BASE = "https://ark.ap-southeast.bytepluses.com/api/v3"
ROOT = Path(os.getenv("CREATIVE_WORKDIR", "/mnt/session/creative-loop"))
VIDEO_RETRIES = 2
# Conservative application policy: unknown and policy errors require inspection.
TRANSIENT_VIDEO_ERRORS = {"InternalError", "InternalServerError", "ServiceUnavailable", "ServerOverloaded"}


def save(state):
    ROOT.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "state.tmp"
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.chmod(0o600)
    tmp.replace(ROOT / "state.json")
    (ROOT / "state.sig").write_text(signature(state))


def load():
    state = json.loads((ROOT / "state.json").read_text())
    if not hmac.compare_digest((ROOT / "state.sig").read_text(), signature(state)):
        raise RuntimeError("State integrity check failed. Never edit state.json directly; stop and report the failure.")
    return state


def signature(state):
    key = os.environ.get("ARK_API_KEY")
    if not key:
        raise RuntimeError("ARK_API_KEY missing")
    return hmac.new(key.encode(), json.dumps(state, sort_keys=True, ensure_ascii=False).encode(), hashlib.sha256).hexdigest()


def response_stream(lines):
    data = []
    for raw in lines:
        line = raw.decode("utf-8").rstrip("\r\n")
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line and data:
            payload = "\n".join(data)
            data = []
            if payload == "[DONE]":
                continue
            event = json.loads(payload)
            if event.get("type") in ("response.failed", "response.incomplete", "error"):
                raise RuntimeError("Responses did not complete: " + event.get("type", "error"))
            if event.get("type") == "response.completed":
                result = event.get("response", {})
                if result.get("status") != "completed":
                    raise RuntimeError("Response completion status missing")
                return result
    raise RuntimeError("SSE ended before response.completed")


def api(path, body=None, stream=False):
    key = os.environ.get("ARK_API_KEY")
    if not key:
        raise RuntimeError("ARK_API_KEY is missing from the Cloud Environment")
    request = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30 if body is None else 240) as response:
                return response_stream(response) if stream else json.load(response)
        except urllib.error.HTTPError as error:
            retryable = error.code == 429 or 500 <= error.code <= 599
            message = "Model API HTTP " + str(error.code)
            error.close()
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            retryable = True
            message = "Model API transport failure"
        # Never repeat a POST with an unknown outcome; GET retries retain task ID.
        if body is not None or not retryable or attempt == 2:
            raise RuntimeError(message) from None
        time.sleep(5 * (2 ** attempt))


def prompts(value):
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or not value[k].strip() or len(value[k]) > 10000 for k in ("design", "mockup", "video")):
        raise ValueError("Three nonempty prompts are required")
    return value


def assert_contract(state):
    if state.get("evidence_contract") != 2 or state.get("contract_hash") != ev.contract_hash(state["brief"], state["criteria"], state.get("watermark")):
        raise ValueError("Frozen acceptance contract is missing or changed; use a new Session")


def selected_round(state):
    evaluated = [r for r in state["rounds"] if "review" in r]
    return evaluated[-1] if state["status"] == "completed" else max(evaluated, key=lambda r: (r["review"]["quality_gate"] == "passed", r["review"]["score"]))


def result_summary(state):
    best = selected_round(state)
    review = best["review"]
    return {"selected_round": best["number"], "score": review["score"],
            "stop_reason": state["status"], "met_target": state["status"] == "completed",
            "score_gap": max(0, round(state["target_score"] - review["score"], 6)),
            "failed_checks": [c for c in review["checks"] if c["status"] == "fail"],
            "unverified_checks": [c for c in review["checks"] if c["status"] == "unverified"],
            "uncovered_requirements": review["uncovered_requirements"]}


def finish_round(state):
    r = state["rounds"][-1]
    r["review"] = ev.effective_review(state["criteria"], r["evaluation"]["report"], r["audit"]["report"], r.get("adjudication", {}).get("report"))
    review = r["review"]
    source = r.get("adjudication", r["evaluation"])
    r["evidence"] = {"text": json.dumps(source["report"], ensure_ascii=False, indent=2),
                     "response_id": source["response_id"]}
    passed = review["quality_gate"] == "passed" and review["score"] >= state["target_score"]
    state["status"] = "blocked" if review["uncovered_requirements"] else "completed" if passed else "max_rounds" if len(state["rounds"]) >= state["max_rounds"] else "needs_revision"
    if state["status"] == "blocked":
        state["error"] = "Acceptance contract omits requirements; start a corrected campaign rather than changing the frozen contract"
    state["best_round"] = selected_round(state)["number"]
    save(state)
    return state["status"]


def evaluate_step(state):
    r = state["rounds"][-1]
    stage = "evaluation" if "evaluation" not in r else "audit" if "audit" not in r else "adjudication" if r["audit"]["report"]["conflicts"] and "adjudication" not in r else None
    if stage is None:
        return finish_round(state)
    attempts = r.get(stage + "_attempts", 0)
    if attempts >= 2:
        raise RuntimeError(stage + " exhausted its two attempts")
    r[stage + "_attempts"] = attempts + 1
    save(state)
    # Each role uses a fresh model context, with no creator reasoning or history.
    body = {"model": os.getenv("EVAL_MODEL", os.getenv("VISION_MODEL", "seed-2-0-lite-260428")), "stream": True,
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": ev.instruction(stage, state["brief"], state["criteria"], r, state.get("watermark"))},
                {"type": "input_image", "image_url": r["design"]["url"]},
                {"type": "input_image", "image_url": r["mockup"]["url"]},
                {"type": "input_video", "video_url": r["video"]["url"], "fps": 1}]}]}
    result = api("/responses", body, stream=True)
    text = "\n".join(c["text"] for item in result.get("output", []) for c in item.get("content", []) if c.get("type") == "output_text")
    report = ev.parse(text)
    if stage == "audit":
        ev.validate_audit(report, state["criteria"])
    elif stage == "adjudication":
        ev.validate_adjudication(report, state["criteria"], r["audit"]["report"])
    else:
        ev.validate_report(report, state["criteria"])
    r[stage] = {"report": report, "response_id": result["id"], "usage": result.get("usage")}
    save(state)
    if stage == "evaluation":
        return "needs_audit"
    if stage == "audit" and report["conflicts"]:
        return "needs_adjudication"
    return finish_round(state)

def advance(state):
    assert_contract(state)
    if state["status"] != "running":
        return state["status"]
    r = state["rounds"][-1]
    if r.get("inflight"):
        raise RuntimeError("Uncertain POST outcome for " + r["inflight"] + "; inspect provider before resubmitting")
    for phase in ("design", "mockup"):
        if phase in r:
            continue
        prompt = r["prompts"][phase]
        prompt += " Deliverable requirements: " + json.dumps([c["description"] for c in state["criteria"] if phase in c["asset_refs"]], ensure_ascii=False)
        body = {"model": os.getenv("IMAGE_MODEL", "seedream-4-5-251128"), "prompt": prompt, "size": "2K", "response_format": "url", "watermark": state.get("watermark", True)}
        if phase == "mockup":
            body["image"] = r["design"]["url"]
        r["inflight"] = phase
        save(state)
        result = api("/images/generations", body)
        r[phase] = {"url": result["data"][0]["url"], "usage": result.get("usage")}
        del r["inflight"]
        save(state)
        return phase + "_completed"
    if "task" not in r:
        time.sleep(max(0, r.get("video_retry_after", 0) - time.time()))
        r["inflight"] = "video"
        save(state)
        result = api("/contents/generations/tasks", {
            "model": os.getenv("VIDEO_MODEL", "dreamina-seedance-2-5-260628"),
            "content": [{"type": "text", "text": r["prompts"]["video"] + " Exactly 5 seconds. No added marketing overlays, invented claims or testimonials. Preserve reference product print."},
                        {"type": "image_url", "image_url": {"url": r["mockup"]["url"]}, "role": "reference_image"}],
            "omni_reference_task_type": "reference", "duration": 5, "ratio": "9:16", "generate_audio": r.get("generate_audio", state.get("generate_audio", False)), "watermark": state.get("watermark", True)})
        r["task"] = result["id"]
        r["submitted_at"] = time.time()
        del r["inflight"]
        save(state)
    if "video" not in r:
        if time.time() - r["submitted_at"] > 1800:
            raise RuntimeError("Video observation exceeded 30 minutes; retained task: " + r["task"])
        deadline = time.time() + 120
        while True:
            result = api("/contents/generations/tasks/" + r["task"])
            if result["status"] in ("succeeded", "failed", "expired", "cancelled") or time.time() >= deadline:
                break
            time.sleep(10)
        if result["status"] in ("failed", "expired", "cancelled"):
            r["provider_error"] = result.get("error", {})
            retries = r.get("video_retries", 0)
            if result["status"] == "failed" and r["provider_error"].get("code") in TRANSIENT_VIDEO_ERRORS and retries < VIDEO_RETRIES:
                r.setdefault("failed_tasks", []).append({"id": r["task"], "error": r["provider_error"], "reason": "transient_retry"})
                r["video_retries"] = retries + 1
                r["video_retry_after"] = time.time() + 5 * (2 ** retries)
                del r["task"]
                r.pop("submitted_at", None)
                save(state)
                return "retrying_video"
            save(state)
            raise RuntimeError("Video task " + result["status"] + ": " + r["provider_error"].get("code", "unknown"))
        if result["status"] != "succeeded":
            return "waiting_video"
        r["video"] = {"url": result["content"]["video_url"], "task": r["task"], "usage": result.get("usage")}
        save(state)
        return "video_completed"
    return evaluate_step(state)

def execute(command, value=None):
    if command == "init":
        if (ROOT / "state.json").exists():
            raise ValueError("Existing loop: resume with step/status; never replace state")
        limit = value.get("max_rounds", 3)
        target = value.get("target_score", 4.5)
        if type(limit) is not int or not 1 <= limit <= 5 or type(target) not in (int, float) or not math.isfinite(target) or not 0 <= target <= 5:
            raise ValueError("Invalid loop limits")
        if type(value.get("generate_audio", False)) is not bool:
            raise ValueError("generate_audio must be boolean")
        watermark = value.get("watermark", True)
        if type(watermark) is not bool:
            raise ValueError("watermark must be boolean")
        rubric = ev.criteria(value.get("criteria"))
        state = {"status": "running", "brief": value["brief"], "research": value.get("research", []), "max_rounds": limit, "target_score": target, "generate_audio": value.get("generate_audio", False),
                 "criteria": rubric, "watermark": watermark, "contract_hash": ev.contract_hash(value["brief"], rubric, watermark),
                 "rounds": [{"number": 1, "prompts": prompts(value["prompts"])}], "execution": "ma_cloud_skill", "evidence_contract": 2}
        save(state)
    else:
        state = load()
        assert_contract(state)
    if command == "retry-silent-video":
        r = state["rounds"][-1]
        if not r.get("task") or r.get("silent_retry_used"):
            raise ValueError("No eligible task or silent retry already used")
        result = api("/contents/generations/tasks/" + r["task"])
        if result.get("status") != "failed" or result.get("error", {}).get("code") != "OutputAudioSensitiveContentDetected.PolicyViolation":
            raise ValueError("Silent replacement is limited to an explicitly failed output-audio task")
        r.setdefault("failed_tasks", []).append({"id":r["task"],"error":result["error"],"reason":"authorized_silent_replacement"})
        r["silent_retry_used"] = True
        r["generate_audio"] = False
        del r["task"]
        r.pop("submitted_at", None)
        state["status"] = "running"
        save(state)
    elif command == "step":
        outcome = advance(state)
    elif command == "review":
        raise ValueError("Manual review is disabled; run step for independent evaluation and audit")
    elif command == "revise":
        if state["status"] != "needs_revision" or len(state["rounds"]) >= state["max_rounds"]:
            raise ValueError("Revision not permitted")
        state["rounds"].append({"number": len(state["rounds"]) + 1, "prompts": prompts(value)})
        state["status"] = "running"
        save(state)
    elif command == "export":
        if state["status"] not in ("completed", "max_rounds", "blocked"):
            raise ValueError("Loop has not finished")
        if not 1 <= len(state["rounds"]) <= state["max_rounds"] or not state.get("best_round"):
            raise ValueError("Invalid final round selection")
        for r in state["rounds"]:
            if not r.get("evidence", {}).get("response_id") or not all(r.get(p, {}).get("url") for p in ("design", "mockup", "video")):
                raise ValueError("Completed assets and actual-media evidence are mandatory")
            if not r.get("evaluation", {}).get("response_id") or not r.get("audit", {}).get("response_id") or (r["audit"]["report"]["conflicts"] and not r.get("adjudication", {}).get("response_id")):
                raise ValueError("Independent review provenance is missing")
            expected = ev.effective_review(state["criteria"], r["evaluation"]["report"], r["audit"]["report"], r.get("adjudication", {}).get("report"))
            if r.get("review") != expected:
                raise ValueError("Review differs from independent evaluation; cannot export")
        best = next(r for r in state["rounds"] if r["number"] == state["best_round"])
        if best["number"] != selected_round(state)["number"]:
            raise ValueError("Selected round does not match return policy")
        if state["status"] == "completed" and (best["review"]["quality_gate"] != "passed" or best["review"]["score"] < state["target_score"]):
            raise ValueError("Completed state does not satisfy evidence gate and target")
        return {**state, "return_policy": "required_pass_then_score_or_early_pass", "result_summary": result_summary(state)}
    outcome = outcome if command == "step" else state["status"]
    return {"status": outcome, "round": len(state["rounds"]), "state_path": str(ROOT / "state.json"),
            "next_action": {
                "needs_revision": "Write three revised prompts, run creative.py revise --input /mnt/session/revised-prompts.json, then continue step.",
                "blocked": "Acceptance contract is incomplete. Export the blocked result, explain the omitted requirements and stop. Do not edit the frozen criteria.",
                "completed": "Run creative.py export and return its exact output.",
                "max_rounds": "Run creative.py export and return its exact output; do not claim the target was met.",
            }.get(outcome, "Run creative.py step again. Evaluation, audit and any adjudication run in independent model contexts; do not supply your own review."),
            "video_retries": state["rounds"][-1].get("video_retries", 0),
            "review": state["rounds"][-1].get("review"), "criteria": state["criteria"],
            "task": state["rounds"][-1].get("task")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "step", "status", "review", "revise", "export", "retry-silent-video"])
    parser.add_argument("--input")
    args = parser.parse_args()
    try:
        value = json.loads(Path(args.input).read_text()) if args.input else None
        print(json.dumps(execute(args.command, value), ensure_ascii=False))
    except Exception as error:
        message = str(error).replace(os.environ.get("ARK_API_KEY", "__NO_KEY__"), "[redacted]")
        print(json.dumps({"status": "error", "error": message[:1000], "state_path": str(ROOT / "state.json")}))
        sys.exit(1)
