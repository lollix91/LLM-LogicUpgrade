"""Benchmark runner for LLM-LogicUpgrade.

Runs each question through both LLM+DALI2 (full pipeline) and pure LLM
(no logic engine), then exports a comparison CSV.

Usage:
    python benchmark/run_benchmark.py [--limit N] [--start N] [--output FILE]

Requirements:
    - Docker services must be running (start.bat / start.sh)
    - The orchestrator must be accessible at http://localhost:8000
"""

import re
import csv
import time
import asyncio
import argparse
from pathlib import Path

import httpx

# --- Configuration ---
ORCHESTRATOR_URL = "http://localhost:8000"
QUESTIONS_FILE = Path(__file__).parent.parent / "domande-risposte-logica.txt"
LOGIC_CSV = Path(__file__).parent / "logic_questions.csv"
DEFAULT_OUTPUT = Path(__file__).parent / "results.csv"

# Questions referencing images/diagrams that we skip
SKIP_PATTERNS = [
    "con riferimento alla figura",
    "individuare il diagramma",
    "osservando la figura",
    "nella figura",
    "il diagramma che",
    "l'immagine",
    "in figura",
    "rappresentazione grafica",
    "il grafico",
]


def parse_questions(filepath: Path) -> list[dict]:
    """Parse all questions from the text file.

    Returns list of dicts: {id, text, options: {A, B, C}, correct_answer}
    """
    content = filepath.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Find where answers section starts
    answers_start = None
    for i, line in enumerate(lines):
        if "RISPOSTE CORRETTE" in line or "CONOSCENZA DELLA LINGUA" in line:
            answers_start = i
            break

    if answers_start is None:
        # Try to find the answer block by pattern (number letter number letter...)
        for i, line in enumerate(lines):
            if re.match(r"^\d+\s+[ABC]\s+\d+\s+[ABC]", line.strip()):
                answers_start = i
                break

    # Parse answers
    answers = {}
    if answers_start is not None:
        for line in lines[answers_start:]:
            # Pattern: "1 A 2 B 3 C 4 A 5 B"
            pairs = re.findall(r"(\d+)\s+([ABC])", line)
            for num, letter in pairs:
                answers[int(num)] = letter

    # Parse questions section (everything before answers)
    question_lines = lines[:answers_start] if answers_start else lines

    questions = []
    current_q = None
    current_text = []
    current_options = {}

    for line in question_lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Skip page markers
        if re.match(r"^Pagina \d+ di\d+$", line_stripped):
            continue

        # New question: starts with "N)" where N is a number
        q_match = re.match(r"^(\d+)\)\s+(.*)", line_stripped)
        if q_match:
            # Save previous question
            if current_q is not None:
                q_text = " ".join(current_text).strip()
                questions.append({
                    "id": current_q,
                    "text": q_text,
                    "options": current_options,
                    "correct_answer": answers.get(current_q, "?"),
                })
            current_q = int(q_match.group(1))
            current_text = [q_match.group(2)]
            current_options = {}
            continue

        # Option line: starts with "A ", "B ", "C "
        opt_match = re.match(r"^([ABC])\s+(.*)", line_stripped)
        if opt_match and current_q is not None:
            current_options[opt_match.group(1)] = opt_match.group(2)
            continue

        # Continuation of current question or option
        if current_q is not None:
            if current_options:
                # Continuation of last option
                last_key = max(current_options.keys())
                current_options[last_key] += " " + line_stripped
            else:
                current_text.append(line_stripped)

    # Save last question
    if current_q is not None:
        q_text = " ".join(current_text).strip()
        questions.append({
            "id": current_q,
            "text": q_text,
            "options": current_options,
            "correct_answer": answers.get(current_q, "?"),
        })

    return questions


def should_skip(question: dict) -> bool:
    """Check if a question should be skipped (e.g., references images)."""
    full_text = question["text"].lower()
    for opt in question.get("options", {}).values():
        full_text += " " + opt.lower()

    for pattern in SKIP_PATTERNS:
        if pattern in full_text:
            return True

    # Skip if no options (malformed)
    if len(question.get("options", {})) < 2:
        return True

    return False


def format_question_prompt(question: dict) -> str:
    """Format a question into a prompt for the LLM."""
    parts = [question["text"]]
    for key in sorted(question.get("options", {}).keys()):
        parts.append(f"{key}) {question['options'][key]}")
    parts.append("\nRispondi indicando solo la lettera della risposta corretta (A, B o C).")
    return "\n".join(parts)


def extract_answer_letter(response: str, question: dict) -> str:
    """Try to extract the chosen answer letter (A/B/C) from the LLM response."""
    # Strip markdown bold/italic markers before matching
    clean = re.sub(r"\*{1,2}", "", response)
    clean = re.sub(r"_{1,2}", "", clean)
    clean_upper = clean.upper().strip()

    # Look for explicit patterns like "La risposta è A", "Risposta: B", etc.
    patterns = [
        r"(?:la\s+)?risposta\s+(?:corretta\s+)?(?:è|e'|:)\s*([ABC])\b",
        r"(?:the\s+)?(?:correct\s+)?answer\s+(?:is|:)\s*([ABC])\b",
        r"\b([ABC])\s*\)\s*(?:è|e'|is)\s+(?:la\s+)?(?:risposta\s+)?corretta",
        r"(?:opzione|option)\s+([ABC])\b",
        r"^([ABC])\s*[\.\)\:]",  # Starts with "A." or "A)" or "A:"
        r"\b([ABC])\s*$",  # Ends with just a letter
    ]

    for pattern in patterns:
        match = re.search(pattern, clean, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).upper()

    # Check if the response contains the text of one specific option
    options = question.get("options", {})
    for letter, text in options.items():
        # If the option text (or significant portion) appears in the response
        if len(text) > 10 and text.lower()[:30] in clean.lower():
            return letter

    # Last resort: look for standalone letter
    letters_found = re.findall(r"\b([ABC])\b", clean_upper)
    if len(letters_found) == 1:
        return letters_found[0]

    return "?"


async def send_question(client: httpx.AsyncClient, prompt: str, skip_logic: bool = False) -> dict:
    """Send a question through the orchestrator.

    Args:
        skip_logic: If True, bypasses DALI2 and uses pure LLM.
    """
    payload = {"message": prompt, "skip_logic": skip_logic}

    try:
        response = await client.post(
            f"{ORCHESTRATOR_URL}/api/chat",
            json=payload,
            timeout=600.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"answer": f"ERROR: {e}", "has_logic": False, "reasoning_trace": []}


async def run_benchmark(questions: list[dict], output_path: Path, start: int = 0, limit: int = None):
    """Run the benchmark: for each question, run both LLM+DALI2 and pure LLM."""
    # Filter and limit
    filtered = [q for q in questions if not should_skip(q)]
    print(f"Total questions: {len(questions)}")
    print(f"After filtering (no images/diagrams): {len(filtered)}")

    if start > 0:
        filtered = [q for q in filtered if q["id"] >= start]
    if limit:
        filtered = filtered[:limit]

    print(f"Running benchmark on {len(filtered)} questions...")
    print(f"Output: {output_path}")
    print("-" * 60)

    results = []

    async with httpx.AsyncClient() as client:
        # Check if orchestrator is reachable
        try:
            health = await client.get(f"{ORCHESTRATOR_URL}/api/health", timeout=5.0)
            health.raise_for_status()
            model = health.json().get("model", "unknown")
            print(f"Orchestrator OK — Model: {model}")
        except Exception as e:
            print(f"ERROR: Cannot reach orchestrator at {ORCHESTRATOR_URL}")
            print(f"  Make sure Docker services are running (start.bat)")
            print(f"  Error: {e}")
            return

        print(f"\n{'#':>4} | {'Expected':^8} | {'LLM+DALI2':^9} | {'Pure LLM':^8} | Question")
        print("-" * 80)

        for i, q in enumerate(filtered):
            prompt = format_question_prompt(q)
            correct = q["correct_answer"]

            # --- Run LLM+DALI2 (full pipeline) ---
            t0 = time.time()
            resp_logic = await send_question(client, prompt, skip_logic=False)
            time_logic = time.time() - t0

            answer_logic = resp_logic.get("answer", "")
            chosen_logic = extract_answer_letter(answer_logic, q)
            if chosen_logic == "?":
                print(f"        [WARN] Q{q['id']} LLM+DALI2: could not extract letter from: {answer_logic[:120]}")

            # Small delay between calls
            await asyncio.sleep(0.3)

            # --- Run pure LLM (no DALI2) ---
            t0 = time.time()
            resp_pure = await send_question(client, prompt, skip_logic=True)
            time_pure = time.time() - t0

            answer_pure = resp_pure.get("answer", "")
            chosen_pure = extract_answer_letter(answer_pure, q)
            if chosen_pure == "?":
                print(f"        [WARN] Q{q['id']} Pure LLM: could not extract letter from: {answer_pure[:120]}")

            # Format question with options for CSV
            options_str = " | ".join(
                f"{k}) {v}" for k, v in sorted(q.get("options", {}).items())
            )
            question_full = f"{q['text']} [{options_str}]"

            result = {
                "question_id": q["id"],
                "question": question_full,
                "expected_answer": correct,
                "llm_dali2_answer": chosen_logic,
                "pure_llm_answer": chosen_pure,
            }
            results.append(result)

            # Console output
            mark_logic = "OK" if chosen_logic == correct else "X" if chosen_logic != "?" else "?"
            mark_pure = "OK" if chosen_pure == correct else "X" if chosen_pure != "?" else "?"
            print(f"  {i+1:>3} | {correct:^8} | {chosen_logic:^4}{mark_logic:^5} | {chosen_pure:^4}{mark_pure:^4} | {q['text'][:50]}")

            # Small delay to avoid overwhelming the system
            await asyncio.sleep(0.5)

    # Write CSV
    if results:
        fieldnames = ["question_id", "question", "expected_answer", "llm_dali2_answer", "pure_llm_answer"]
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        # Print summary
        total = len(results)
        correct_logic = sum(1 for r in results if r["llm_dali2_answer"] == r["expected_answer"])
        correct_pure = sum(1 for r in results if r["pure_llm_answer"] == r["expected_answer"])

        print("\n" + "=" * 60)
        print("BENCHMARK RESULTS")
        print("=" * 60)
        print(f"Total questions:        {total}")
        print(f"LLM+DALI2 correct:      {correct_logic}/{total} ({100*correct_logic/total:.1f}%)")
        print(f"Pure LLM correct:       {correct_pure}/{total} ({100*correct_pure/total:.1f}%)")
        print(f"Difference:             {correct_logic - correct_pure:+d}")
        print(f"")
        print(f"Results saved to: {output_path}")


def load_from_csv(csv_path: Path) -> list[dict]:
    """Load questions from the pre-filtered logic_questions.csv."""
    questions = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            questions.append({
                "id": int(row["id"]),
                "text": row["question"],
                "options": {
                    "A": row.get("option_A", ""),
                    "B": row.get("option_B", ""),
                    "C": row.get("option_C", ""),
                },
                "correct_answer": row["correct_answer"],
            })
    return questions


def main():
    parser = argparse.ArgumentParser(description="Run LLM-LogicUpgrade benchmark")
    parser.add_argument("--limit", type=int, default=None, help="Max number of questions to test")
    parser.add_argument("--start", type=int, default=0, help="Start from question ID N")
    parser.add_argument("--output", type=str, default=None, help="Output CSV path")
    parser.add_argument("--questions", type=str, default=None, help="Path to questions file (txt or csv)")
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else DEFAULT_OUTPUT

    # Load questions: prefer pre-filtered CSV, fallback to full txt
    if args.questions:
        questions_path = Path(args.questions)
    elif LOGIC_CSV.exists():
        questions_path = LOGIC_CSV
    else:
        questions_path = QUESTIONS_FILE

    if not questions_path.exists():
        print(f"ERROR: Questions file not found: {questions_path}")
        return

    if questions_path.suffix == ".csv":
        print(f"Loading pre-filtered questions from: {questions_path}")
        questions = load_from_csv(questions_path)
        print(f"Loaded {len(questions)} logic questions")
    else:
        print(f"Parsing questions from: {questions_path}")
        questions = parse_questions(questions_path)
        print(f"Parsed {len(questions)} questions with answers")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(run_benchmark(questions, output_path, start=args.start, limit=args.limit))


if __name__ == "__main__":
    main()
