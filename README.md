# LLM-LogicUpgrade

> Augment LLM reasoning with formal logic — powered by DALI2

LLM-LogicUpgrade demonstrates how a **base LLM** (without "thinking" or chain-of-thought) can improve its logical reasoning capabilities by delegating formal inference to the **DALI2** symbolic logic engine. The LLM acts as a *formalizer* — it translates natural-language problems into structured logic — while DALI2 performs the actual reasoning and determines the correct answer.

## How It Works

The system uses an **option evaluation** architecture for multiple-choice questions (MCQ):

1. The LLM extracts facts, rules, and a **testable claim for each answer option** (JSON)
2. The orchestrator compiles these into a Prolog program with `option_valid(Key) :- Claim` rules
3. DALI2 evaluates **all options in a single call** via `findall` — determining which are logically provable
4. The pipeline selects the answer based on the question type (e.g., "find the true conclusion" → the provable option)

```
User Question (MCQ)
    │
    ▼
[Step 1] LLM formalizes: facts + rules + option_claims (JSON)
    │
    ▼
[Step 2] Translator builds: option_valid(a) :- claim_a, ... + findall query
    │
    ▼
[Step 3] DALI2 evaluates all options → returns provable set [a, c, ...]
    │
    ▼
[Step 4] Pipeline determines answer from provable/unprovable options
    │
    ▼
Answer (letter) → Web UI / Benchmark
```

### Key Design Principles

- **LLM does NOT solve the problem** — it only formalizes premises and maps options to logical claims
- **DALI2 does the actual reasoning** — symbolic inference determines which conclusions follow
- **No "thinking" mode** — demonstrates that a base LLM + symbolic logic outperforms the LLM alone
- **Single DALI2 call per question** — all options tested simultaneously via `findall`
- **Graceful fallback** — if DALI2 can't determine the answer, falls back to pure LLM

### Question Types

| Type | Logic | Answer Selection |
|------|-------|------------------|
| `find_true_conclusion` | Which option follows from premises? | The unique provable option |
| `find_not_necessarily_true` | Which option does NOT follow? | The unique unprovable option |
| `find_false_conclusion` | Which option contradicts premises? | The unique unprovable option |
| `compute_value` | Arithmetic/calculation with explicit A/B/C options | The option whose value matches |
| `compute_answer` | Open-ended computation (no A/B/C options) | DALI2 binds the result variable |
| `find_same_mistake` | Which option commits the same fallacy? | The option whose fallacy atom matches |
| `find_argument_loophole` | Which option illustrates the argument's gap? | The option whose concern atom matches |
| `has_logic: false` | Strengthen/weaken, definitions, assumptions, reading comprehension | Falls back to pure LLM |

### Extended IR (Intermediate Representation)

The LLM outputs a structured JSON that supports:

| Construct | JSON IR | Prolog |
|-----------|---------|--------|
| Negation | `{"not": <term>}` | `\+(Goal)` |
| Disjunction | `{"or": [<terms>]}` | `(A ; B)` |
| Conjunction | `{"and": [<terms>]}` | `(A , B)` |
| Arithmetic | `{"pred": "is", "args": ["X", "A+B"]}` | `X is A+B` |
| Findall | `{"findall": T, "goal": G, "bag": V}` | `findall(T, G, V)` |
| Forall | `{"forall": C, "action": A}` | `forall(C, A)` |
| Aggregates | `{"aggregate": "count", ...}` | `findall + length` |
| If-then-else | `{"if_then_else": C, "then": T, "else": E}` | `(C -> T ; E)` |
| Lists | JSON arrays `["a", "b"]` | `[a, b]` |
| Member | `{"pred": "member", "args": [X, ["a","b"]]}` | `member(X, [a, b])` |
| Between | `{"pred": "between", "args": [1, 100, X]}` | `between(1, 100, X)` |

### Graceful Degradation

If DALI2 cannot determine a unique answer (ambiguous evaluation, formalization error, or engine failure), the system falls back to a direct LLM response rather than returning an incorrect answer.

### Validation Pipeline

Before sending a formalized problem to DALI2, the orchestrator runs two validation layers:

1. **Structural validation** (`validate_program`) — checks that every predicate referenced in option claims and rule bodies is reachable from declared facts or rule heads. Catches undefined predicates (e.g., `count/2`, `equals/2`) before they reach the engine.
2. **Enhanced validation** (`validate_enhanced`) — arity consistency, variable safety (head-only variables), cycle detection (recursive rules without base cases), and query groundness potential.

If validation fails, the error feedback (with repair hints) is sent back to the LLM for a retry (up to 3 attempts). This prevents malformed programs from silently failing in DALI2.

## Quick Start

### Prerequisites

- **Docker** (with Docker Compose)
- **One of:**
  - **NVIDIA GPU** with ≥12GB VRAM + NVIDIA Container Toolkit — for local inference
  - **OpenRouter API key** — for cloud inference (no GPU required)

#### GPU Setup (Local mode only)

<details>
<summary>Windows</summary>

- **Docker Desktop** with WSL2 backend
- NVIDIA Container Toolkit is bundled with Docker Desktop on Windows
</details>

<details>
<summary>Linux (Ubuntu/Debian)</summary>

1. Install NVIDIA drivers:
   ```bash
   sudo apt update && sudo apt install -y nvidia-driver-535 && sudo reboot
   ```

2. Add the NVIDIA Container Toolkit repository:
   ```bash
   curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
     sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

   curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
     sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
     sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
   ```

3. Install and configure:
   ```bash
   sudo apt update && sudo apt install -y nvidia-container-toolkit
   sudo nvidia-ctk runtime configure --runtime=docker
   sudo systemctl restart docker
   ```

4. Verify:
   ```bash
   sudo docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
   ```
</details>

### Start (Local — Ollama)

**Windows:**
```bat
start.bat
```

**Linux:**
```bash
chmod +x start.sh
./start.sh
```

This starts all Docker services (Redis, Ollama, DALI2, Orchestrator, Web UI) and pulls the LLM model (~6.6GB first time).

### Start (Cloud — OpenRouter)

No GPU required. Uses [OpenRouter](https://openrouter.ai) for LLM inference.

**Windows:**
```bat
start.bat --openrouter-key sk-or-v1-YOUR_KEY_HERE
```

**Linux:**
```bash
./start.sh --openrouter-key sk-or-v1-YOUR_KEY_HERE
```

Optionally specify a different model:
```bash
./start.sh --openrouter-key sk-or-v1-... --openrouter-model qwen/qwen3-32b
```

Default model: `qwen/qwen3.5-9b` (~$0.10/M input, $0.15/M output). In OpenRouter mode, only Redis, DALI2, Orchestrator, and Web UI are started (Ollama is skipped).

### Stop

**Windows:** `stop.bat` · **Linux:** `./stop.sh`

## Services

| Service | Port | Description |
|---------|------|-------------|
| Web UI | 3000 | Chat interface with reasoning trace |
| Orchestrator | 8000 | FastAPI pipeline (API docs at `/docs`) |
| DALI2 | 8080 | Logic engine (SWI-Prolog) |
| Ollama | 11434 | LLM inference server (local mode only) |
| Redis | 6379 | Message bus |

## Configuration

Copy `.env.example` to `.env` and edit as needed:

```env
OLLAMA_MODEL=qwen3.5:9b          # Local model (Ollama)
NVIDIA_VISIBLE_DEVICES=all        # GPU selection

# OpenRouter (set via start.bat --openrouter-key or manually)
OPENROUTER_API_KEY=               # Leave empty for local mode
OPENROUTER_MODEL=qwen/qwen3.5-9b # Cloud model override
```

The model can also be changed at runtime from the Web UI settings panel.

## Architecture

```
┌──────────┐    ┌──────────────┐    ┌─────────────────────┐
│  Web UI  │◄──►│ Orchestrator │◄──►│  Ollama (local GPU) │
│  :3000   │    │  :8000       │    │  OR OpenRouter API  │
└──────────┘    └──────┬───────┘    └─────────────────────┘
                       │
                       ▼
                ┌──────────────┐    ┌──────────┐
                │    DALI2     │◄──►│  Redis   │
                │  :8080       │    │  :6379   │
                └──────────────┘    └──────────┘
```

### Pipeline Components

- **`orchestrator/app/pipeline.py`** — Core orchestration: extraction → validation → option evaluation via DALI2 → answer determination. Includes retry with error feedback (up to 3 attempts). Both MCQ and legacy paths include validation before DALI2 submission.
- **`orchestrator/app/translator.py`** — JSON IR to Prolog compiler + `build_option_eval_event()` for MCQ evaluation. Supports negation, disjunction, arithmetic, findall, forall, aggregates, lists, if-then-else. Includes `validate_program()` with MCQ-aware validation (checks option claim predicates are reachable).
- **`orchestrator/app/validator.py`** — Static analysis: arity consistency, variable safety, cycle detection, repair hints.
- **`orchestrator/app/llm_client.py`** — Dual-backend LLM client (Ollama local / OpenRouter cloud). Thinking mode disabled.
- **`orchestrator/app/prompts/extraction.md`** — Formalizer prompt with 24 worked examples covering syllogisms, contrapositives, quantifiers, arithmetic, ordering, biconditionals, "only if", double negation, combinatorial constraints, multi-step chains, fallacy matching, argument loopholes, and guidance on when to use `has_logic: false` (strengthen/weaken, definitions, assumptions).
- **`orchestrator/app/prompts/synthesis.md`** — Minimal synthesis prompt (MCQ answers bypass this entirely).
- **`orchestrator/app/schemas.py`** — Legacy reasoning schemas (backward compatibility for non-MCQ use).
- **`orchestrator/app/theories.py`** — Composable micro-theory library (12 theories).
- **`dali2-agents/logic_solver.pl`** — DALI2 agent with extended meta-interpreter (SLD + arithmetic + lists + findall + forall + if-then-else + between/3 + succ/2 + plus/3 + type checks). Supports generate-and-test for combinatorial/constraint problems.

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/chat` | Send a message through the reasoning pipeline (`skip_logic=true` bypasses DALI2) |
| `GET` | `/api/capabilities` | List available schemas and micro-theories |
| `GET` | `/api/health` | Health check (model, backend) |
| `GET` | `/api/model` | Current and available models |
| `POST` | `/api/model` | Change active model |
| `GET/POST/DELETE` | `/api/conversations/*` | Conversation management |

Full API docs at `http://localhost:8000/docs` (Swagger UI).

## Benchmark

A benchmark suite compares **LLM+DALI2** (full neuro-symbolic pipeline) against **pure LLM** (no logic engine) on standardized logic questions.

### Datasets

| File | Language | Options | Questions |
|------|----------|---------|-----------|
| `benchmark/logic_questions_en.csv` | English | A/B/C/D | ~7400 |
| `benchmark/logic_questions_it.csv` | Italian | A/B/C | ~370 |

The script **auto-detects** the number of options from the CSV header (supports any number of `option_X` columns).

### Run the benchmark

```bash
# English benchmark (default)
python benchmark/run_benchmark.py

# Italian benchmark
python benchmark/run_benchmark.py --questions benchmark/logic_questions_it.csv

# Limit to N questions
python benchmark/run_benchmark.py --limit 50

# Start from question ID
python benchmark/run_benchmark.py --start 10 --limit 20

# Custom output path
python benchmark/run_benchmark.py --output benchmark/my_results.csv

# Combine options
python benchmark/run_benchmark.py --questions benchmark/logic_questions_en.csv --limit 100 --output benchmark/en_100.csv
```

### Requirements

- Docker services must be running (`start.bat` or `start.sh`)
- The orchestrator must be accessible at `http://localhost:8000`

### How it works

For each question the benchmark sends **two requests** to the orchestrator:
1. `skip_logic=False` — full pipeline (LLM formalization → DALI2 evaluation → answer)
2. `skip_logic=True` — direct LLM response (no logic engine)

Output CSV columns: `question_id`, `question`, `expected_answer`, `llm_dali2_answer`, `pure_llm_answer`.

A summary with accuracy percentages and the delta between both modes is printed at the end.

## License

Apache License 2.0