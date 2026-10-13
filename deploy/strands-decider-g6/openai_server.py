"""OpenAI-compatible /v1/chat/completions in front of the strands-decider System One engine.

strands-decider is a decision model: it scores the options of typed questions
(noul = yes/no, choice = one of N, score = ordered level) and never generates free
text. This wrapper keeps the official routes (/health, /v1/systemone) and maps a chat
completion onto one System One call:

  state      <- the chat messages (a lone user message is used verbatim; otherwise
                "role: content" lines)
  questions  <- one of, in priority order:
     1. top-level "questions" (OpenAI SDK: extra_body={"questions": {...}}), native format
     2. response_format {"type":"json_schema"}: boolean property -> noul,
        string enum property -> choice (optional "x-descriptions": {option: text}),
        integer property with "x-levels": [..] -> score
     3. last user message whose content is JSON {"state"?: ..., "questions": {...}}
  reply      <- choices[0].message.content is JSON. With json_schema it is an object
                that matches the schema (bool / enum value / level index); otherwise it
                is the full typed answers. Full probabilities are always in "decider".
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from strands_decider.schema import SystemOneRequest
from strands_decider.server import create_app, get_engine

CHECKPOINT = os.environ.get("DECIDER_CHECKPOINT", "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610")
MODEL_NAME = os.environ.get("DECIDER_MODEL_NAME") or CHECKPOINT.rstrip("/").rsplit("/", 1)[-1]
API_KEY = os.environ.get("DECIDER_API_KEY") or None  # optional bearer key
DEVICE = os.environ.get("DECIDER_DEVICE", "cuda")
# Batch caps are forwarded only when set: strands-decider 0.1.0's create_app has no such parameters.
_batch = {k: int(os.environ[e]) for k, e in (("max_batch", "DECIDER_MAX_BATCH"),
                                             ("max_batch_tokens", "DECIDER_MAX_BATCH_TOKENS"))
          if os.environ.get(e)}

app = create_app(CHECKPOINT, device=DEVICE, model_name=MODEL_NAME, **_batch)
_lock = threading.Lock()  # one GPU engine; serialise calls from the threadpool
_created = int(time.time())


def _err(status: int, message: str, typ: str = "invalid_request_error", param: str | None = None):
    return JSONResponse(status_code=status,
                        content={"error": {"message": message, "type": typ, "param": param, "code": None}})


@app.middleware("http")
async def _auth(request: Request, call_next):
    if API_KEY and request.url.path.startswith("/v1/"):
        if request.headers.get("authorization", "") != f"Bearer {API_KEY}":
            return _err(401, "Invalid API key", "authentication_error")
    return await call_next(request)


@app.get("/v1/models")
def list_models() -> dict:
    return {"object": "list", "data": [
        {"id": MODEL_NAME, "object": "model", "created": _created, "owned_by": "strands-labs"}]}


class BadRequest(ValueError):
    def __init__(self, message: str, param: str | None = None):
        super().__init__(message)
        self.param = param


def _text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(p.get("text", ""))
            else:
                raise BadRequest("only text content parts are supported", "messages")
        return "\n".join(parts)
    raise BadRequest("unsupported message content", "messages")


def _state_from_messages(messages: list[dict]) -> str:
    turns = [(m.get("role", "user"), _text(m.get("content"))) for m in messages]
    turns = [(r, c) for r, c in turns if c.strip()]
    if not turns:
        raise BadRequest("messages contain no text", "messages")
    if len(turns) == 1 and turns[0][0] == "user":
        return turns[0][1]
    return "\n\n".join(f"{r}: {c}" for r, c in turns)


def _questions_from_schema(rf: dict) -> tuple[dict, dict]:
    js = rf.get("json_schema") or {}
    schema = js.get("schema") or {}
    props = schema.get("properties") or {}
    if schema.get("type", "object") != "object" or not props:
        raise BadRequest("json_schema must be an object schema with properties", "response_format")
    questions, kinds = {}, {}
    for name, p in props.items():
        instr = p.get("description") or p.get("title") or name
        if p.get("type") == "boolean":
            questions[name] = {"type": "noul", "instructions": instr}
            kinds[name] = "bool"
        elif "enum" in p and all(isinstance(v, str) for v in p["enum"]):
            # Same as the official CLI: options without a description get "". An optional
            # "x-descriptions": {option: text} sharpens the boundary between options.
            desc = p.get("x-descriptions") or {}
            questions[name] = {"type": "choice", "instructions": instr,
                               "criteria": {v: str(desc.get(v, "")) for v in p["enum"]}}
            kinds[name] = "enum"
        elif p.get("type") == "integer" and isinstance(p.get("x-levels"), list):
            questions[name] = {"type": "score", "instructions": instr, "criteria": p["x-levels"]}
            kinds[name] = "level"
        else:
            raise BadRequest(f"property '{name}': use boolean, a string enum, or integer with "
                             "x-levels (decision models cannot generate free text)", "response_format")
    return questions, kinds


def _plan(body: dict) -> tuple[Any, dict, dict | None]:
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise BadRequest("messages must be a non-empty list", "messages")
    if body.get("n", 1) != 1:
        raise BadRequest("only n=1 is supported", "n")
    if body.get("tools"):
        raise BadRequest("tools are not supported; ask a choice question over the tool names", "tools")
    rf = body.get("response_format") or {}
    if body.get("questions"):
        return _state_from_messages(messages), body["questions"], None
    if rf.get("type") == "json_schema":
        q, kinds = _questions_from_schema(rf)
        return _state_from_messages(messages), q, kinds
    last = messages[-1]
    if last.get("role") == "user":
        try:
            obj = json.loads(_text(last.get("content")))
        except (json.JSONDecodeError, BadRequest):
            obj = None
        if isinstance(obj, dict) and obj.get("questions"):
            state = obj.get("state")
            if state is None:
                state = _state_from_messages(messages[:-1])
            return state, obj["questions"], None
    raise BadRequest("no questions: pass response_format json_schema (boolean / string enum "
                     "properties), a top-level 'questions' object, or a last user message with "
                     "JSON {\"state\", \"questions\"}. This is a decision model; it does not "
                     "generate free text.", "messages")


def _content(answers: dict, kinds: dict | None) -> str:
    if kinds is None:
        return json.dumps(answers, ensure_ascii=False)
    out = {}
    for name, kind in kinds.items():
        a = answers[name]
        if kind == "bool":
            out[name] = a["noul"] >= 0.5
        elif kind == "enum":
            out[name] = a["choice"]
        else:
            out[name] = int(max(a["probabilities"].items(), key=lambda kv: kv[1])[0])
    return json.dumps(out, ensure_ascii=False)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except Exception:
        return _err(400, "request body must be JSON")
    try:
        state, questions, kinds = _plan(body)
        req = SystemOneRequest.model_validate({"state": state, "questions": questions})
    except BadRequest as exc:
        return _err(400, str(exc), param=exc.param)
    except Exception as exc:  # pydantic validation of questions
        return _err(400, f"invalid questions: {exc}", param="questions")

    def run():
        with _lock:
            return get_engine().evaluate(req)

    import anyio
    started = time.perf_counter()
    try:
        resp = await anyio.to_thread.run_sync(run)
    except ValueError as exc:
        return _err(422, str(exc), param="questions")
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    answers = resp.model_dump()["answers"]
    content = _content(answers, kinds)
    cid, now = f"chatcmpl-{uuid.uuid4().hex}", int(time.time())
    usage = {"prompt_tokens": resp.usage.input_tokens, "completion_tokens": 0,
             "total_tokens": resp.usage.input_tokens}
    decider = {"answers": answers, "latency_ms": latency_ms}

    if body.get("stream"):
        def sse():
            base = {"id": cid, "object": "chat.completion.chunk", "created": now, "model": MODEL_NAME}
            yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {
                "role": "assistant", "content": content}, "finish_reason": None}]}) + "\n\n"
            last = {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "decider": decider}
            if (body.get("stream_options") or {}).get("include_usage"):
                last["usage"] = usage
            yield "data: " + json.dumps(last) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(sse(), media_type="text/event-stream")

    return JSONResponse({
        "id": cid, "object": "chat.completion", "created": now, "model": MODEL_NAME,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop", "logprobs": None}],
        "usage": usage, "decider": decider,
    })
