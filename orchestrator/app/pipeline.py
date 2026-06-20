"""Multi-step reasoning pipeline: LLM extraction → DALI2 logic → LLM synthesis."""

import json
import time
import asyncio
from pathlib import Path

from app import llm_client, dali2_client
from app.translator import build_query_event, parse_dali2_result, parse_dali2_logs, validate_program, compile_program
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

    Flow: extract (structured JSON) -> validate connectivity -> DALI2 solve ->
    self-consistency check (DALI2 result vs LLM expectation). On failure, retry
    extraction with specific feedback. Finally synthesize the answer.

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
    logic_result: dict | None = None

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

        # --- Step 1b: Build program from schema (or keep free-form) ---
        schema = extraction.get("schema")
        if schema:
            program, schema_err = build_from_schema(schema, extraction.get("slots", {}))
            if program is None:
                error_feedback = schema_err
                if attempt < MAX_ATTEMPTS - 1:
                    continue
                break
            extraction.update(program)

        # --- Step 1c: Structural validation (connectivity) ---
        validation = validate_program(extraction)
        if not validation["valid"]:
            error_feedback = validation["reason"]
            # Generate repair hints for more specific feedback
            hints = generate_repair_hints(validation, extraction)
            if hints:
                error_feedback += " HINTS: " + "; ".join(hints)
            if attempt < MAX_ATTEMPTS - 1:
                continue
            break

        # --- Step 1d: Enhanced validation (arity, safety, cycles) ---
        enhanced = validate_enhanced(extraction)
        if not enhanced["valid"]:
            error_feedback = enhanced["reason"]
            hints = enhanced.get("hints", [])
            if hints:
                error_feedback += " HINTS: " + "; ".join(hints)
            if attempt < MAX_ATTEMPTS - 1:
                continue
            break

        # Log validation warnings (if any) in the trace
        all_warnings = enhanced.get("warnings", [])
        if all_warnings:
            trace.append(PipelineStep(
                step="validation_warnings",
                title="Validation Warnings",
                content="\n".join(f"⚠ {w}" for w in all_warnings),
                duration_ms=0,
            ))

        # --- Step 2: DALI2 Logic Solving ---
        t2 = time.time()
        logic_result = await _solve_with_dali2(extraction)
        t3 = time.time()
        print(f"[TIMING] Attempt {attempt} | DALI2: {t3-t2:.1f}s | solved={logic_result.get('solved')}", flush=True)

        trace.append(PipelineStep(
            step="dali2_solving",
            title="DALI2 Logic Engine",
            content=json.dumps(logic_result, indent=2, ensure_ascii=False),
            duration_ms=round((t3 - t2) * 1000, 1),
        ))

        # --- Step 2b: Self-consistency check ---
        # Skip for option_selection: DALI2 trivially confirms whatever goal we set
        if extraction.get("schema") == "option_selection":
            logic_result["consistent"] = True
            print(f"[TIMING] Attempt {attempt} | Consistency: True (option_selection, skip check)", flush=True)
            break

        consistent, reason = _check_consistency(logic_result, extraction.get("expected_answer"))
        logic_result["consistent"] = consistent
        print(f"[TIMING] Attempt {attempt} | Consistency: {consistent} | reason={reason[:80] if reason else 'ok'}", flush=True)
        if consistent:
            break
        error_feedback = reason
        # otherwise loop and retry (unless out of attempts)

    # === Determine response path ===

    # Path 1: Verified logic solution
    if (extraction.get("has_logic") and logic_result
            and logic_result.get("consistent")):
        t4 = time.time()
        answer = await _synthesize_answer(
            user_message, extraction, logic_result, conversation_history,
            verified=True,
        )
        t5 = time.time()
        print(f"[TIMING] Synthesis (verified): {t5-t4:.1f}s", flush=True)
        trace.append(PipelineStep(
            step="synthesis",
            title="Final Answer Synthesis",
            content="Answer generated using verified logical solution.",
            duration_ms=round((t5 - t4) * 1000, 1),
        ))
        return {"answer": answer, "has_logic": True, "reasoning_trace": trace}

    # Path 2: Elegant degradation — logic detected but engine failed;
    # use the LLM's own explanation (which is often correct even when
    # formalisation fails) instead of discarding it.
    if extraction.get("has_logic") and extraction.get("explanation"):
        soft_result = {
            "status": "explanation_fallback",
            "solved": True,
            "solution": extraction.get("expected_answer", "unknown"),
            "explanation": extraction["explanation"],
        }
        t4 = time.time()
        answer = await _synthesize_answer(
            user_message, extraction, soft_result, conversation_history,
            verified=False,
        )
        t5 = time.time()
        print(f"[TIMING] Synthesis (fallback): {t5-t4:.1f}s", flush=True)
        trace.append(PipelineStep(
            step="synthesis",
            title="Explanation-Based Synthesis",
            content=(
                "Logic engine could not verify the solution. "
                "Using the extraction's natural-language explanation as basis."
            ),
            duration_ms=round((t5 - t4) * 1000, 1),
        ))
        return {"answer": answer, "has_logic": True, "reasoning_trace": trace}

    # Path 3: No logic detected → direct LLM response
    t4 = time.time()
    answer = await _direct_response(user_message, conversation_history)
    t5 = time.time()
    print(f"[TIMING] Direct response: {t5-t4:.1f}s", flush=True)
    trace.append(PipelineStep(
        step="direct_response",
        title="Direct LLM Response",
        content="No logical reasoning required — responding directly.",
        duration_ms=round((t5 - t4) * 1000, 1),
    ))
    return {"answer": answer, "has_logic": False, "reasoning_trace": trace}


def _check_consistency(logic_result: dict, expected) -> tuple[bool, str]:
    """Compare DALI2's solution against the LLM's expected answer.

    This is the neuro-symbolic verification step: the symbolic engine confirms
    the neural intuition. Returns (consistent, feedback_for_retry).
    """
    if not logic_result.get("solved"):
        return False, (
            "DALI2 could not prove the query. Ensure the query predicate matches a "
            "rule head, and that every rule-body predicate is a fact or another rule "
            "head, forming a chain facts -> rules -> query."
        )

    solution = str(logic_result.get("solution", "")).strip().lower()
    exp = str(expected or "").strip().lower()

    if not exp:
        return True, ""  # no expectation provided -> accept any proof

    affirmative = {"yes", "true", "si", "sì", "vero"}
    if exp in affirmative:
        return True, ""  # ground query proven true is sufficient

    if exp in solution:
        return True, ""  # expected binding appears in the solution term

    return False, (
        f"DALI2 derived '{logic_result.get('solution')}' but you expected '{expected}'. "
        f"Re-examine the modeling: encode the correct common-sense effects so the engine "
        f"derives the right answer (model all options; let the rules select the valid one)."
    )


async def _extract_logic(user_message: str, error_feedback: str | None = None) -> dict:
    """Step 1: Ask LLM to extract a structured logical model (JSON)."""
    user_content = user_message
    if error_feedback:
        user_content = (
            f"{user_message}\n\n"
            f"[SYSTEM FEEDBACK] Your previous extraction was rejected: {error_feedback}\n"
            f"Produce a corrected JSON model. Make sure the query is derivable from the "
            f"facts and rules, and model every option explicitly."
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
    """Step 2: Send logic to DALI2 and get the solution."""
    try:
        # Build the event to inject
        event = build_query_event(extraction)

        # Inject the solve event into the logic_solver agent
        await dali2_client.inject_event("logic_solver", event)

        # Wait for DALI2 to process (give it a couple cycles)
        await asyncio.sleep(1)

        # Get logs (always available via Redis sync)
        logs = await dali2_client.get_logs("logic_solver")

        # Try beliefs API first (works in non-distributed mode)
        beliefs = await dali2_client.get_beliefs("logic_solver")
        result = parse_dali2_result(beliefs)

        # Fall back to parsing logs (distributed mode: beliefs live in
        # the agent process, not the server, so the API returns empty)
        if not result["solved"]:
            result = parse_dali2_logs(logs)

        if result["solved"]:
            # Discard stale "query_failed" explanation from previous runs
            explanation = result.get("explanation")
            if explanation == "query_failed":
                explanation = None
            return {
                "status": "solved",
                "solved": True,
                "solution": result["solution"],
                "bindings": result["bindings"],
                "explanation": explanation,
                "logs": logs[-10:] if logs else [],
            }
        else:
            # Fallback: use the extraction's own explanation
            return {
                "status": "used_extraction",
                "solved": False,
                "solution": compile_program(extraction)["query"],
                "explanation": extraction.get("explanation", ""),
                "logs": logs[-10:] if logs else [],
            }

    except Exception as e:
        # If DALI2 is unavailable, use extraction explanation as fallback
        return {
            "status": "fallback",
            "solution": compile_program(extraction)["query"],
            "explanation": extraction.get("explanation", "Logic engine unavailable, using LLM extraction."),
            "error": str(e),
        }


async def _synthesize_answer(
    user_message: str,
    extraction: dict,
    logic_result: dict,
    history: list[dict],
    verified: bool = True,
) -> str:
    """Step 3: Generate final answer using the logic solution."""
    logic_summary = (
        f"Problem: {extraction.get('explanation', 'N/A')}\n"
        f"Solution: {logic_result.get('solution', 'N/A')}\n"
        f"Explanation: {logic_result.get('explanation', 'N/A')}"
    )
    if logic_result.get("bindings"):
        logic_summary += f"\nBindings: {', '.join(logic_result['bindings'])}"

    if verified:
        header = "The following logical reasoning has been formally verified:"
    else:
        header = (
            "The following reasoning was extracted but could NOT be formally "
            "verified by the logic engine. Use it as strong guidance but "
            "apply your own judgment:"
        )

    system_prompt = SYNTHESIS_PROMPT.replace(
        "The following logical reasoning has been formally verified:", header
    ).replace("{logic_result}", logic_summary)

    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history (last 10 messages)
    for msg in history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_message})

    return await llm_client.chat(messages, temperature=0.7, think=False, max_tokens=1024)


async def _direct_response(user_message: str, history: list[dict]) -> str:
    """Direct LLM response when no logic is detected."""
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Answer in the same language as the user."},
    ]

    for msg in history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_message})

    return await llm_client.chat(messages, temperature=0.7, think=False, max_tokens=1024)
