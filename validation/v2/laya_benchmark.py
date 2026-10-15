"""One serial, no-retry Laya run on the Tokyo GPU host. Raw responses are retained."""
import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from llm_baseline import grade, load_items
from run import JEV

V2 = Path(__file__).resolve().parent
REQUESTS = V2 / "llm-requests-laya-20261015.json"
CONTROLS = {"model": "multilingual", "max_len": 8192, "head_max_len": 256}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def prepare():
    items = load_items()
    fixes = {i["id"]: i for i in load_items(V2 / "llm-requests-ui-fix-20261013.json")}
    items = [fixes.get(i["id"], i) for i in items]
    assert len(items) == 76 and len({i["id"] for i in items}) == 76
    with REQUESTS.open("x") as out:
        json.dump(items, out, ensure_ascii=False, indent=2)
        out.write("\n")
    print(fingerprint(items))


def call(request, endpoint):
    # The local oracle is never included in the wire body.
    body = {**CONTROLS, "state": request["state"], "questions": request["questions"]}
    wire = json.dumps(body, ensure_ascii=False).encode()
    started = time.perf_counter()
    req = urllib.request.Request(endpoint + "/v1/systemone", data=wire,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as response:
        raw = json.loads(response.read())
    wall = time.perf_counter() - started
    return raw, wall, fingerprint(body)


def run(output, endpoint, deployment, smoke=False):
    items = load_items(REQUESTS)
    if smoke:
        items = [{"id": "warmup:billing", "skill": "smoke",
                  "request": {"model": "typesafe/jev-1.13", "state": "我的信用卡被重复扣款，请帮我退款。",
                              "questions": {"team": {"type": "choice", "instructions": "谁应该处理这个问题？",
                                                    "criteria": {"billing": "账单、付款、退款", "tech": "软件故障"}}}},
                  "grade": {"kind": "one_of", "question": "team", "accept": ["billing"]}}] * 3
    manifest = json.loads(deployment.read_text())
    with urllib.request.urlopen(endpoint + "/health", timeout=10) as response:
        health = json.loads(response.read())
    assert health["device"] == "cuda" and not health["device_is_preference"], health
    assert not any(v["count"] for v in health.get("cpu_fallbacks", {}).values()), health
    assert len(items) <= 76
    calls, stop = 0, None
    with output.open("x", encoding="utf-8") as out:
        def record(row):
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
        record({"kind": "manifest", "backend": "laya", "styles": ["native"], "region": "ap-northeast-1",
                "model_id": "convaiinnovations/laya-multilingual", "api": "systemone",
                "instance": manifest["instance"], "deployment": manifest, "health": health,
                "requests": len(items), "requests_file": REQUESTS.name, "requests_sha256": fingerprint(items),
                "concurrency": 1, "retries": 0, "controls": CONTROLS, "endpoint": endpoint,
                "timing_scope": "HTTP loopback on Tokyo GPU host; warm service; includes JSON transport",
                "smoke": smoke, "price_in_per_m": "0", "price_out_per_m": "0",
                "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        started = time.perf_counter()
        for item in items:
            calls += 1
            try:
                raw, wall, wire_hash = call(item["request"], endpoint)
                # Persist the full response even if schema validation fails.
                record({"kind": "raw_response", "id": item["id"], "wall_seconds": wall,
                        "wire_sha256": wire_hash, "response": raw})
                report = JEV.build_report(item["request"], raw)
                decisions = report["decisions"]
                answers = {qid: decision["value"] for qid, decision in decisions.items()}
                record({"kind": "llm_result", "style": "native", "id": item["id"], "skill": item["skill"],
                        "answers": answers, "decisions": decisions, "raw_answers": raw["answers"],
                        "usage": {"inputTokens": raw["usage"]["input_tokens"], "outputTokens": raw["usage"]["output_tokens"]},
                        "wall_seconds": wall, "latency_ms": wall * 1000, "has_reasoning": False,
                        "stop_reason": "end_turn", "graded": grade(item, answers), "cost_usd": "0",
                        "parse_error": None})
            except Exception as error:
                stop = f"{type(error).__name__}: {error}"
                if isinstance(error, urllib.error.HTTPError):
                    stop += ": " + error.read().decode(errors="replace")
                record({"kind": "error", "id": item["id"], "error": stop})
                break
        wall = time.perf_counter() - started
        record({"kind": "style_wall", "style": "native", "wall_seconds": wall})
        try:
            with urllib.request.urlopen(endpoint + "/health", timeout=10) as response:
                health_after = json.loads(response.read())
            record({"kind": "health_after", "health": health_after})
            if health_after["device"] != "cuda" or any(v["count"] for v in health_after.get("cpu_fallbacks", {}).values()):
                stop = stop or "GPU validation failed: CPU fallback detected"
        except Exception as error:
            stop = stop or f"Post-run health check failed: {error}"
        record({"kind": "summary", "calls": calls, "cost_usd": "0", "stop_reason": stop})
        print(json.dumps({"calls": calls, "wall_seconds": wall, "stop": stop}))
    if stop:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "smoke"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000")
    parser.add_argument("--deployment", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    else:
        if not args.output or not args.deployment:
            parser.error("--output and --deployment are required")
        run(args.output, args.endpoint, args.deployment, smoke=args.command == "smoke")
