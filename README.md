# LLM-LogicUpgrade

> Augment LLM reasoning with formal logic — powered by DALI2

LLM-LogicUpgrade intercepts user prompts, extracts logical constructs using an LLM, solves them with the DALI2 logic engine (Prolog meta-interpreter), and delivers logically-validated responses.

## How It Works

The system uses a **schema-based slot-filling** approach: the LLM never writes Prolog rules. Instead, it identifies a reasoning pattern (schema) and fills in flat data slots. The orchestrator generates correct, connected Prolog programs from those slots — eliminating the entire class of LLM Prolog-syntax errors.

```
User Prompt
    │
    ▼
[Step 1] LLM picks a reasoning schema and fills slots (JSON)
    │
    ▼
[Step 2] Orchestrator builds Prolog from schema + validates connectivity
    │
    ▼
[Step 3] DALI2 solves the logic formally
    │
    ▼
[Step 4] LLM synthesizes final answer with verified logical solution
    │
    ▼
Response + Reasoning Trace → Web UI
```

### Reasoning Schemas

| Schema | Pattern | Example |
|--------|---------|---------|
| `option_selection` | Which option achieves the goal? | "Walk or drive to the car wash?" |
| `classification` | Is X a Y? (category hierarchy) | "Tom is a cat. Is Tom an animal?" |
| `comparison` | Which item is best/worst? | "Route A is 10km, Route B is 25km. Which is shorter?" |
| `deduction` | If-then, biconditional (iff) | "If and only if it rains, I open my umbrella. Does it rain?" |
| `composed` | Combine micro-theories | "Mario is Luigi's father, Luigi is Paolo's. Is Mario an ancestor?" |
| `freeform` | Generic FOL (fallback) | Any first-order logic expressible as facts + rules + query |

### Composable Micro-Theories

The `composed` schema allows combining specialized reasoning modules:

| Theory | Handles |
|--------|---------|
| `transitive_closure` | Hierarchies, ancestry, reachability |
| `disjunctive_exclusion` | "Either A or B. Not A → B" |
| `arithmetic_compare` | Numeric max/min with real values |
| `counting` | "How many X satisfy Y?" |
| `temporal_ordering` | Before/after with transitivity |
| `modus_tollens` | Contraposition: A→B, ¬B ⊢ ¬A |
| `set_membership` | "All/some/none of X have Y" |
| `constraint_assignment` | Puzzle-like assignments |
| `causal_chain` | Cause→effect propagation |
| `default_exception` | "Birds fly, penguins don't" |
| `spatial_reasoning` | Left/right/above/below + transitivity |
| `planning` | STRIPS-like action selection |

Each schema/theory generates fixed Prolog rules that are correct and connected by construction. The LLM only provides flat facts (slot values).

### Elegant Degradation

If DALI2 cannot verify the solution (e.g., schema mismatch, engine timeout), the system falls back to the LLM's natural-language explanation rather than discarding it. The response is marked as unverified.

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

- **`orchestrator/app/schemas.py`** — Reasoning schema definitions (option_selection, classification, comparison, deduction, freeform, composed)
- **`orchestrator/app/theories.py`** — Composable micro-theory library (12 theories: transitive_closure, disjunctive_exclusion, arithmetic_compare, etc.)
- **`orchestrator/app/translator.py`** — Extended JSON-to-Prolog compiler (supports negation, disjunction, arithmetic, findall, forall, aggregates)
- **`orchestrator/app/validator.py`** — Enhanced static analysis: arity consistency, variable safety, cycle detection, repair hints
- **`orchestrator/app/pipeline.py`** — Multi-step orchestration: extraction → schema build → validation → DALI2 solve → consistency check → synthesis
- **`orchestrator/app/llm_client.py`** — Dual-backend LLM client (Ollama local / OpenRouter cloud)
- **`orchestrator/app/prompts/extraction.md`** — LLM prompt for schema/theory selection and slot-filling (15 examples)
- **`orchestrator/app/prompts/synthesis.md`** — LLM prompt for answer synthesis with logic result
- **`dali2-agents/logic_solver.pl`** — DALI2 agent with extended meta-interpreter (SLD + arithmetic + lists + findall + forall + if-then-else)

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

### Build the dataset

```bash
python benchmark/build_logic_dataset.py
```

Filters ~370 logic-relevant questions (syllogisms, conditionals, ordering, negation, arithmetic) from the full 1500-question bank, excluding vocabulary, reading comprehension, and visual questions.

### Run the benchmark

```bash
# Full benchmark
python benchmark/run_benchmark.py

# Limit to N questions
python benchmark/run_benchmark.py --limit 50

# Start from question ID
python benchmark/run_benchmark.py --start 100 --limit 20

# Custom output
python benchmark/run_benchmark.py --output benchmark/my_results.csv
```

For each question the benchmark sends two requests to the orchestrator:
1. `skip_logic=False` — full pipeline (LLM extraction → DALI2 → synthesis)
2. `skip_logic=True` — direct LLM response (no logic engine)

Output CSV columns: `question_id`, `question`, `expected_answer`, `llm_dali2_answer`, `pure_llm_answer`.

A summary with accuracy percentages for both modes is printed at the end.

## License

Apache License 2.0
