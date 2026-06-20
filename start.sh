#!/bin/bash

OPENROUTER_KEY=""
OPENROUTER_MODEL_ARG=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --openrouter-key)
            OPENROUTER_KEY="$2"
            shift 2
            ;;
        --openrouter-model)
            OPENROUTER_MODEL_ARG="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

echo "============================================"
echo "  LLM-LogicUpgrade - Starting..."
echo "============================================"
echo ""

# Copy .env if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[INFO] Created .env from .env.example"
    echo ""
fi

if [ -n "$OPENROUTER_KEY" ]; then
    # --- OpenRouter mode ---
    echo "[MODE] OpenRouter - using cloud API"

    # Update .env with OpenRouter settings
    grep -v "OPENROUTER_API_KEY\|OPENROUTER_MODEL" .env > .env.tmp
    echo "OPENROUTER_API_KEY=$OPENROUTER_KEY" >> .env.tmp
    if [ -n "$OPENROUTER_MODEL_ARG" ]; then
        echo "OPENROUTER_MODEL=$OPENROUTER_MODEL_ARG" >> .env.tmp
    fi
    mv .env.tmp .env

    echo ""
    echo "[1/2] Starting Docker services (no Ollama)..."
    docker compose up -d --build redis dali2 orchestrator web-ui

    echo ""
    echo "[2/2] Waiting for orchestrator..."
    while ! curl -s http://localhost:8000/api/health > /dev/null 2>&1; do
        sleep 2
    done

    echo ""
    echo "============================================"
    echo "  LLM-LogicUpgrade is ready! [OpenRouter]"
    echo ""
    echo "  Web UI:       http://localhost:3000"
    echo "  Orchestrator: http://localhost:8000/docs"
    echo "  DALI2:        http://localhost:8080"
    echo "  Backend:      OpenRouter"
    echo "============================================"
else
    # --- Standard local mode ---
    echo "[MODE] Local Ollama"

    # Start all services
    echo "[1/3] Starting Docker services..."
    docker compose up -d --build

    echo ""
    echo "[2/3] Waiting for Ollama to be ready..."
    while ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do
        sleep 2
    done

    echo "[3/3] Pulling LLM model (first time may take a while)..."
    OLLAMA_MODEL=$(grep OLLAMA_MODEL .env 2>/dev/null | cut -d'=' -f2)
    if [ -z "$OLLAMA_MODEL" ]; then
        OLLAMA_MODEL="qwen3.5:9b"
    fi
    docker compose exec -T ollama ollama pull "$OLLAMA_MODEL"

    echo ""
    echo "============================================"
    echo "  LLM-LogicUpgrade is ready! [Local]"
    echo ""
    echo "  Web UI:       http://localhost:3000"
    echo "  Orchestrator: http://localhost:8000/docs"
    echo "  DALI2:        http://localhost:8080"
    echo "  Ollama:       http://localhost:11434"
    echo "============================================"
fi
