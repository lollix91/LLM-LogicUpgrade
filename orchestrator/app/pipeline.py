"""Multi-step reasoning pipeline: LLM extraction → DALI2 logic → LLM synthesis."""

import json
import re
import time
import asyncio
from pathlib import Path

from app import llm_client, dali2_client
from app.translator import build_query_event, build_option_eval_event, parse_dali2_result, parse_dali2_logs, validate_program, compile_program
from app.schemas import build_from_schema, available_schemas
from app.theories import available_theories
from app.validator import validate_enhanced, generate_repair_hints
from app.models import PipelineStep

MAX_ATTEMPTS = 3

_prompts_dir = Path(__file__).parent / "prompts"
EXTRACTION_PROMPT = (_prompts_dir / "extraction.md").read_text()
SYNTHESIS_PROMPT = (_prompts_dir / "synthesis.md").read_text()


async def run_pipeline(user_message: str, conversation_history: list[dict], skip_logic: bool = False) -> dict:
    """Execute the full neuro-symbolic reasoning pipeline.

    New flow (option evaluation):
      extract (structured JSON with option_claims) → build combined program →
      DALI2 evaluates all options → determine answer based on question_type →
      synthesize response.

    If skip_logic=True, bypass the logic engine and respond directly via LLM.
    """
    trace = []

    if skip_logic:
        answer = await _direct_response(user_message, conversation_history)
        trace.append(PipelineStep(
            step="direct_response",
            title="Direct LLM Response (skip_logic)",
            content="Logic pipeline skipped by request.",
            duration_ms=0,
        ))
        return {"answer": answer, "has_logic": False, "reasoning_trace": trace}

    error_feedback = None
    extraction: dict = {}
    determined_answer: str | None = None

    for attempt in range(MAX_ATTEMPTS):
        # --- Step 1: Logic Extraction ---
        t0 = time.time()
        extraction = await _extract_logic(user_message, error_feedback)
        t1 = time.time()
        print(f"[TIMING] Attempt {attempt} | Extraction: {t1-t0:.1f}s", flush=True)

        title = "Logic Extraction" if attempt == 0 else f"Logic Extraction (retry {attempt})"
        trace.append(PipelineStep(
            step="extraction",
            title=title,
            content=json.dumps(extraction, indent=2, ensure_ascii=False),
            duration_ms=round((t1 - t0) * 1000, 1),
        ))

        if not extraction.get("has_logic"):
            break

        # --- Step 1b: Check for option_claims (new MCQ path) ---
        if extraction.get("option_claims"):
            # New architecture: evaluate each option via DALI2
            t2 = time.time()
            eval_result = await _evaluate_options(extraction)
            t3 = time.time()
            print(f"[TIMING] Attempt {attempt} | Option eval: {t3-t2:.1f}s | valid={eval_result.get('valid_options')}", flush=True)

            trace.append(PipelineStep(
                step="dali2_option_eval",
                title="DALI2 Option Evaluation",
                content=json.dumps(eval_result, indent=2, ensure_ascii=False),
                duration_ms=round((t3 - t2) * 1000, 1),
            ))

            determined_answer = _determine_answer(
                eval_result.get("valid_options", []),
                extraction.get("question_type", "find_true_conclusion"),
                list(extraction["option_claims"].keys()),
            )

            if determined_answer:
                print(f"[TIMING] Attempt {attempt} | Determined answer: {determined_answer}", flush=True)
                break
            else:
                error_feedback = (
                    f"Option evaluation inconclusive: valid_options={eval_result.get('valid_options')}. "
                    f"Ensure exactly ONE option is provable (for find_true/compute_value) or "
                    f"exactly ONE is unprovable (for find_not_necessarily_true). "
                    f"Check that facts+rules correctly encode the premises and that "
                    f"option_claims correctly represent each answer choice."
                )
                if attempt < MAX_ATTEMPTS - 1:
                    continue
                break
        else:
            # Legacy path: schema-based (for non-MCQ or backward compat)
            schema = extraction.get("schema")
            if schema:
                program, schema_err = build_from_schema(schema, extraction.get("slots", {}))
                if program is None:
                    error_feedback = schema_err
                    if attempt < MAX_ATTEMPTS - 1:
                        continue
                    break
                extraction.update(program)

            validation = validate_program(extraction)
            if not validation["valid"]:
                error_feedback = validation["reason"]
                hints = generate_repair_hints(validation, extraction)
                if hints:
                    error_feedback += " HINTS: " + "; ".join(hints)
                if attempt < MAX_ATTEMPTS - 1:
                    continue
                break

            enhanced = validate_enhanced(extraction)
            if not enhanced["valid"]:
                error_feedback = enhanced["reason"]
                hints = enhanced.get("hints", [])
                if hints:
                    error_feedback += " HINTS: " + "; ".join(hints)
                if attempt < MAX_ATTEMPTS - 1:
                    continue
                break

            # Legacy DALI2 solve
            t2 = time.time()
            logic_result = await _solve_with_dali2(extraction)
            t3 = time.time()
            print(f"[TIMING] Attempt {attempt} | DALI2 (legacy): {t3-t2:.1f}s | solved={logic_result.get('solved')}", flush=True)
            trace.append(PipelineStep(
                step="dali2_solving",
                title="DALI2 Logic Engine",
                content=json.dumps(logic_result, indent=2, ensure_ascii=False),
                duration_ms=round((t3 - t2) * 1000, 1),
            ))
            if logic_result.get("solved"):
                determined_answer = str(logic_result.get("solution", ""))
                break
            error_feedback = "DALI2 could not solve the query. Check facts and rules connectivity."
            if attempt < MAX_ATTEMPTS - 1:
                continue
            break

    # === Determine response path ===

    # Path 1: Logic engine determined an answer
    if extraction.get("has_logic") and determined_answer:
        t4 = time.time()
        answer = await _synthesize_answer(
            user_message, extraction, determined_answer, conversation_history,
        )
        t5 = time.time()
        print(f"[TIMING] Synthesis (verified): {t5-t4:.1f}s", flush=True)
        trace.append(PipelineStep(
            step="synthesis",
            title="Final Answer Synthesis",
            content=f"Logic engine determined answer: {determined_answer}",
            duration_ms=round((t5 - t4) * 1000, 1),
        ))
        return {"answer": answer, "has_logic": True, "reasoning_trace": trace}

    # Path 2: Logic detected but engine could not determine → fall back to direct LLM
    t4 = time.time()
    answer = await _direct_response(user_message, conversation_history)
    t5 = time.time()
    print(f"[TIMING] Direct response (fallback): {t5-t4:.1f}s", flush=True)
    trace.append(PipelineStep(
        step="direct_response",
        title="Direct LLM Response (fallback)",
        content="Logic engine could not determine answer — responding directly.",
        duration_ms=round((t5 - t4) * 1000, 1),
    ))
    return {"answer": answer, "has_logic": False, "reasoning_trace": trace}


def _determine_answer(valid_options: list, question_type: str, all_keys: list) -> str | None:
    """Determine the final answer from DALI2's option evaluation results.

    Args:
        valid_options: list of option keys that were provable (e.g. ["a", "c"])
        question_type: the extraction's question_type field
        all_keys: all option keys (e.g. ["A", "B", "C"])

    Returns the answer key (uppercase) or None if inconclusive.
    """
    # Normalize to uppercase
    valid_upper = {v.upper() for v in valid_options}
    all_upper = {k.upper() for k in all_keys}
    not_valid = all_upper - valid_upper

    if question_type in ("find_true_conclusion", "compute_value", "find_same_mistake", "find_argument_loophole"):
        # The answer is the provable option
        if len(valid_upper) == 1:
            return valid_upper.pop()
        # Heuristic: if 2 are valid and 1 isn't, might be a "find_not" mislabel
        # Fall through to heuristic below

    elif question_type in ("find_not_necessarily_true", "find_false_conclusion"):
        # The answer is the UNprovable option
        if len(not_valid) == 1:
            return not_valid.pop()
        # Heuristic: if only 1 is valid and 2 aren't, might be a "find_true" mislabel
        # Fall through to heuristic below

    # --- Heuristic fallback based on counts ---
    if question_type in ("find_true_conclusion", "compute_value", "find_same_mistake", "find_argument_loophole"):
        # For "find true": if 2+ are valid, we can't determine uniquely → fail
        # But if exactly 1 is valid (caught above), return it
        # If 0 are valid, fail
        return None
    elif question_type in ("find_not_necessarily_true", "find_false_conclusion"):
        # For "find not true": if 2+ are not valid, we can't determine → fail
        # If exactly 1 is not valid (caught above), return it
        # If 0 not valid, fail
        return None

    # Unknown question_type — try both heuristics
    if len(valid_upper) == 1:
        return valid_upper.pop()
    if len(not_valid) == 1:
        return not_valid.pop()

    return None


async def _evaluate_options(extraction: dict) -> dict:
    """Evaluate all MCQ options against the logical model using DALI2.

    Builds a combined program with option_valid(Key) rules and uses findall
    to collect which options are provable in a single DALI2 call.
    """
    try:
        event = build_option_eval_event(extraction)

        await dali2_client.inject_event("logic_solver", event)
        await asyncio.sleep(1.5)

        logs = await dali2_client.get_logs("logic_solver")
        beliefs = await dali2_client.get_beliefs("logic_solver")
        result = parse_dali2_result(beliefs)

        if not result["solved"]:
            result = parse_dali2_logs(logs)

        valid_options = _parse_valid_options(result.get("solution", ""))

        return {
            "status": "evaluated",
            "valid_options": valid_options,
            "raw_solution": result.get("solution", ""),
            "logs": logs[-15:] if logs else [],
        }

    except Exception as e:
        return {
            "status": "error",
            "valid_options": [],
            "error": str(e),
        }


def _parse_valid_options(solution_str: str) -> list[str]:
    """Parse the findall result to extract which options were valid.

    The solution should look like: [a,b] or [a] or [] or valid_options([a,c])
    """
    if not solution_str:
        return []

    s = str(solution_str).strip()

    # Handle wrapper: valid_options([a,b,c])
    m = re.search(r"valid_options\(\[([^\]]*)\]\)", s)
    if m:
        s = f"[{m.group(1)}]"

    # Handle direct list: [a,b,c]
    m = re.search(r"\[([^\]]*)\]", s)
    if m:
        content = m.group(1).strip()
        if not content:
            return []
        items = [x.strip().strip("'\"") for x in content.split(",")]
        return [x for x in items if x]

    # Handle single atom
    if s in ("a", "b", "c", "d"):
        return [s]

    return []


async def _extract_logic(user_message: str, error_feedback: str | None = None) -> dict:
    """Step 1: Ask LLM to extract a structured logical model (JSON)."""
    user_content = user_message
    if error_feedback:
        user_content = (
            f"{user_message}\n\n"
            f"[SYSTEM FEEDBACK] Your previous extraction was rejected: {error_feedback}\n"
            f"Produce a corrected JSON model."
        )
    messages = [
        {"role": "system", "content": EXTRACTION_PROMPT},
        {"role": "user", "content": user_content},
    ]

    response = await llm_client.chat(messages, temperature=0.3, think=False, max_tokens=2048)

    # Parse JSON from response (handle markdown code blocks)
    json_str = response.strip()
    if json_str.startswith("```"):
        lines = json_str.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        json_str = "\n".join(lines)

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError:
        # Try to find JSON in the response
        start = json_str.find("{")
        end = json_str.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                result = json.loads(json_str[start:end])
            except json.JSONDecodeError:
                return {"has_logic": False}
        else:
            return {"has_logic": False}

    return result


async def _solve_with_dali2(extraction: dict) -> dict:
    """Legacy Step 2: Send logic to DALI2 and get the solution."""
    try:
        event = build_query_event(extraction)
        await dali2_client.inject_event("logic_solver", event)
        await asyncio.sleep(1)

        logs = await dali2_client.get_logs("logic_solver")
        beliefs = await dali2_client.get_beliefs("logic_solver")
        result = parse_dali2_result(beliefs)

        if not result["solved"]:
            result = parse_dali2_logs(logs)

        if result["solved"]:
            return {
                "status": "solved",
                "solved": True,
                "solution": result["solution"],
                "bindings": result["bindings"],
                "logs": logs[-10:] if logs else [],
            }
        else:
            return {
                "status": "failed",
                "solved": False,
                "logs": logs[-10:] if logs else [],
            }

    except Exception as e:
        return {"status": "error", "solved": False, "error": str(e)}


async def _synthesize_answer(
    user_message: str,
    extraction: dict,
    determined_answer: str,
    history: list[dict],
) -> str:
    """Step 3: Generate final answer using the logic-determined result.

    For MCQ (option_claims present), just return the letter directly
    to avoid the LLM contradicting the logic engine's determination.
    """
    if extraction.get("option_claims"):
        # Direct answer for MCQ — no need for synthesis LLM call
        return determined_answer

    # For non-MCQ (legacy), use synthesis LLM
    logic_summary = f"The logic engine has determined the answer is: {determined_answer}"
    system_prompt = SYNTHESIS_PROMPT.replace("{logic_result}", logic_summary)

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    return await llm_client.chat(messages, temperature=0.3, think=False, max_tokens=512)


async def _direct_response(user_message: str, history: list[dict]) -> str:
    """Direct LLM response when no logic is detected or as fallback."""
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Answer in the same language as the user."},
    ]

    for msg in history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_message})

    return await llm_client.chat(messages, temperature=0.7, think=False, max_tokens=1024)
