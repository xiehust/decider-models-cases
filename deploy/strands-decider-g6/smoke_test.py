"""Smoke test for the OpenAI-compatible decider API. Standard library only.

usage: python3 smoke_test.py http://<private-ip>:8000 [api-key]
"""
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
KEY = sys.argv[2] if len(sys.argv) > 2 else None
STATE = "Help! My payouts have been failing for 3 days!"


def call(path, body=None):
    headers = {"content-type": "application/json"}
    if KEY:
        headers["authorization"] = f"Bearer {KEY}"
    req = urllib.request.Request(BASE + path, headers=headers, method="POST" if body else "GET",
                                 data=json.dumps(body).encode() if body else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


failures = []


def check(name, cond, detail):
    print(("PASS " if cond else "FAIL ") + name + ": " + json.dumps(detail, ensure_ascii=False)[:300])
    if not cond:
        failures.append(name)


s, models = call("/v1/models")
check("models", s == 200 and models["data"], models)
model = models["data"][0]["id"]

schema = {"type": "json_schema", "json_schema": {"name": "triage", "schema": {
    "type": "object",
    "properties": {
        "team": {"type": "string", "enum": ["billing", "sales", "retail"],
                 "description": "Which team should handle this?"},
        "urgent": {"type": "boolean", "description": "Does this convey urgency?"},
        "frustration": {"type": "integer", "x-levels": ["calm", "frustrated", "depressed"],
                        "description": "How frustrated is the writer?"}},
    "required": ["team", "urgent", "frustration"]}}}
s, r = call("/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content": STATE}],
                                     "response_format": schema})
content = json.loads(r["choices"][0]["message"]["content"]) if s == 200 else {}
check("json_schema", s == 200 and content.get("team") == "billing" and isinstance(content.get("urgent"), bool),
      {"content": content, "probs": r.get("decider", {}).get("answers", {}).get("team")})

s, r = call("/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content": STATE}],
                                     "questions": {"is_urgent": {"type": "noul",
                                                                 "instructions": "Does this convey urgency?"}}})
ans = json.loads(r["choices"][0]["message"]["content"]) if s == 200 else {}
check("native_questions", s == 200 and 0 <= ans.get("is_urgent", {}).get("noul", -1) <= 1, ans)

s, r = call("/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content": "hello"}]})
check("free_text_rejected_400", s == 400 and "error" in r, r)

sys.exit(1 if failures else 0)
