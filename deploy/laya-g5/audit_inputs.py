"""Audit actual Laya token construction before inference; never evaluates model answers."""
import argparse
import json
from pathlib import Path

from huggingface_hub import snapshot_download
from transformers import AutoTokenizer
from laya.agent import Agent
from laya.common import _encode_question_text, build_sequence, render_options

MODEL = "convaiinnovations/laya-multilingual"
REVISION = "1720e3e3357cfe1e281542e223f8273b0890ca34"


def audit(requests):
    checkpoint = snapshot_download(MODEL, revision=REVISION, allow_patterns=["tokenizer/*"])
    tokenizer = AutoTokenizer.from_pretrained(str(Path(checkpoint) / "tokenizer"))
    rows = []
    for item in json.loads(requests.read_text()):
        for qid, definition in item["request"]["questions"].items():
            question = Agent._to_internal(definition)
            for budget in [256, 1024]:
                seq, markers, options, state = build_sequence(
                    tokenizer, item["request"]["state"], question,
                    max_len=8192, head_max_len=budget,
                    return_stats=True, return_truncation_stats=True)
                full_instruction = _encode_question_text(
                    tokenizer, f'{question["t"]} question: {question["ins"]}'.replace(tokenizer.mask_token, " "),
                    add_special_tokens=False)
                full_options = [_encode_question_text(
                    tokenizer, " " + text.replace(tokenizer.mask_token, " "), add_special_tokens=False)
                    for text in render_options(question)]
                option_lengths = [b - a - 1 for a, b in zip(markers, markers[1:])]
                # Last option ends at the head's closing SEP immediately before state.
                head_len = len(seq) - state["state_tokens_used"] - 1
                option_lengths.append(head_len - markers[-1] - 2)
                rows.append({
                    "id": item["id"], "question": qid, "head_max_len": budget,
                    "sequence_tokens": len(seq), "state": state, "options": options,
                    "instruction_tokens": len(full_instruction),
                    "instruction_tokens_dropped": max(0, len(full_instruction) - (markers[0] - 2)),
                    "option_tokens_dropped": [max(0, len(a) - b) for a, b in zip(full_options, option_lengths)],
                })
    summary = {}
    for budget in [256, 1024]:
        group = [r for r in rows if r["head_max_len"] == budget]
        summary[str(budget)] = {
            "questions": len(group), "max_sequence_tokens": max(r["sequence_tokens"] for r in group),
            "state_truncated": sum(r["state"]["truncated"] for r in group),
            "instruction_truncated": sum(r["instruction_tokens_dropped"] > 0 for r in group),
            "options_truncated": sum(any(r["option_tokens_dropped"]) for r in group),
            "options_collapsed": sum(r["options"]["options_distinct"] < r["options"]["options"] for r in group),
        }
    return {"model": MODEL, "revision": REVISION, "max_len": 8192, "summary": summary, "questions": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requests", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.requests)
    with args.output.open("x") as out:
        json.dump(result, out, ensure_ascii=False, indent=2)
        out.write("\n")
    print(json.dumps(result["summary"], indent=2))
