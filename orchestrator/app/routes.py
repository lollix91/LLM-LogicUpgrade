from fastapi import APIRouter, HTTPException

from app import llm_client
from app.models import (
    ChatRequest,
    ChatResponse,
    ModelChangeRequest,
    ModelInfo,
    ConversationSummary,
    ConversationDetail,
)
from app.pipeline import run_pipeline
from app.schemas import available_schemas
from app.theories import available_theories
from app.history import (
    create_conversation,
    update_conversation_title,
    add_message,
    list_conversations,
    get_conversation,
    delete_conversation,
)

router = APIRouter()


# --- Chat ---


@router.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Process a user message through the logic-augmented pipeline."""
    # Get or create conversation
    conv_id = request.conversation_id
    history = []

    try:
        if conv_id:
            conv = get_conversation(conv_id)
            if conv:
                history = conv["messages"]
            else:
                conv_id = create_conversation()
        else:
            conv_id = create_conversation()

        # Save user message
        add_message(conv_id, "user", request.message)
    except Exception as e:
        print(f"[WARN] DB error (user msg): {e}", flush=True)
        if not conv_id:
            conv_id = "tmp-" + str(id(request))

    # Run pipeline
    result = await run_pipeline(request.message, history, skip_logic=request.skip_logic)

    try:
        # Save assistant response
        trace_dicts = [step.model_dump() for step in result["reasoning_trace"]]
        add_message(
            conv_id,
            "assistant",
            result["answer"],
            reasoning_trace=trace_dicts,
            has_logic=result["has_logic"],
        )

        # Auto-title on first message
        if not history:
            title = request.message[:50] + ("..." if len(request.message) > 50 else "")
            update_conversation_title(conv_id, title)
    except Exception as e:
        print(f"[WARN] DB error (assistant msg): {e}", flush=True)

    return ChatResponse(
        conversation_id=conv_id,
        answer=result["answer"],
        has_logic=result["has_logic"],
        reasoning_trace=result["reasoning_trace"],
    )


# --- Conversations ---


@router.get("/api/conversations", response_model=list[ConversationSummary])
async def get_conversations():
    """List all conversations."""
    return list_conversations()


@router.get("/api/conversations/{conv_id}", response_model=ConversationDetail)
async def get_conversation_detail(conv_id: str):
    """Get a specific conversation with all messages."""
    conv = get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.delete("/api/conversations/{conv_id}")
async def remove_conversation(conv_id: str):
    """Delete a conversation."""
    delete_conversation(conv_id)
    return {"status": "ok"}


# --- Model Management ---


@router.get("/api/model", response_model=ModelInfo)
async def get_model_info():
    """Get current model and available models."""
    models = await llm_client.list_models()
    return ModelInfo(
        current_model=llm_client.get_model(),
        available_models=models,
    )


@router.post("/api/model")
async def change_model(request: ModelChangeRequest):
    """Change the active LLM model."""
    # Check if model exists
    models = await llm_client.list_models()
    if request.model not in models:
        # Try to pull it
        success = await llm_client.pull_model(request.model)
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Model '{request.model}' not found and could not be pulled",
            )

    llm_client.set_model(request.model)
    return {"status": "ok", "model": request.model}


@router.post("/api/model/pull")
async def pull_model(request: ModelChangeRequest):
    """Pull a new model into Ollama."""
    success = await llm_client.pull_model(request.model)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to pull model '{request.model}'")
    return {"status": "ok", "model": request.model}


# --- Capabilities ---


@router.get("/api/capabilities")
async def capabilities():
    """List available reasoning schemas and micro-theories."""
    return {
        "schemas": available_schemas(),
        "theories": available_theories(),
    }


# --- Health ---


@router.get("/api/health")
async def health():
    """Health check."""
    return {"status": "ok", "model": llm_client.get_model(), "backend": llm_client.get_backend()}
