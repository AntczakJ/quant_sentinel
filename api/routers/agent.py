"""
api/routers/agent.py — FastAPI router dla Quant Sentinel Gold Trader Agent.

Endpointy:
  POST /api/agent/chat              — wysyła wiadomość i odbiera odpowiedź agenta
  POST /api/agent/thread            — tworzy nową sesję (zwraca pusty thread_id)
  GET  /api/agent/thread/{id}       — pobiera historię wiadomości sesji
  GET  /api/agent/info              — informacje o agencie i dostępnych narzędziach
  GET  /api/agent/config            — eksportuje konfigurację agenta

Uwaga: thread_id jest teraz response_id z Responses API (nie Assistants API thread).
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


# ==================== MODELE PYDANTIC ====================

class ChatRequest(BaseModel):
    message: str = Field(..., description="Wiadomość do agenta")
    thread_id: Optional[str] = Field(None, description="ID wątku (None = nowy wątek)")


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    run_id: str
    tool_calls: list = []


class ThreadResponse(BaseModel):
    thread_id: str


# ==================== HELPER ====================

def _get_agent():
    """Pobiera agenta lub rzuca 503 jeśli niedostępny."""
    from src.integrations.openai_agent import get_agent
    agent = get_agent()
    if not agent:
        raise HTTPException(
            status_code=503,
            detail="Agent niedostępny — upewnij się że OPENAI_API_KEY jest ustawiony w .env",
        )
    return agent


# ==================== ENDPOINTY ====================

@router.post("/chat", response_model=ChatResponse, summary="Wyślij wiadomość do agenta")
async def chat_with_agent(request: ChatRequest):
    """
    Wysyła wiadomość do Quant Sentinel Gold Trader i odbiera odpowiedź.

    Agent pamięta historię rozmowy w ramach thread_id.
    Przekaż ten sam thread_id w kolejnych żądaniach żeby kontynuować rozmowę.
    Pomiń thread_id żeby rozpocząć nową sesję.
    """
    agent = _get_agent()
    try:
        result = await asyncio.to_thread(agent.chat, request.message, request.thread_id)
        return ChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd agenta: {str(e)}")


@router.post("/thread", response_model=ThreadResponse, summary="Utwórz nowy wątek")
async def create_thread():
    """Tworzy nowy pusty wątek rozmowy i zwraca jego thread_id."""
    agent = _get_agent()
    try:
        thread_id = await asyncio.to_thread(agent.create_thread)
        return ThreadResponse(thread_id=thread_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/thread/{thread_id}", summary="Historia wątku")
async def get_thread_history(thread_id: str, limit: int = 20):
    """
    Pobiera historię wiadomości w danym wątku.
    Zwraca posortowane chronologicznie pary user/assistant.
    """
    agent = _get_agent()
    try:
        history = await asyncio.to_thread(agent.get_thread_history, thread_id, limit)
        return {"thread_id": thread_id, "messages": history, "count": len(history)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/info", summary="Informacje o agencie")
async def get_agent_info():
    """Zwraca informacje o agencie: nazwę, model, dostępność i listę narzędzi."""
    from src.integrations.openai_agent import get_agent, AGENT_NAME, AGENT_MODEL, AGENT_TOOLS_SCHEMA
    agent = get_agent()
    return {
        "name":      AGENT_NAME,
        "model":     AGENT_MODEL,
        "available": agent is not None,
        "api":       "responses",  # Responses API (migracja z Assistants API)
        "tools":     [t["name"] for t in AGENT_TOOLS_SCHEMA],
    }


@router.get("/config", summary="Eksport konfiguracji dla Agent Builder")
async def get_agent_config():
    """
    Eksportuje pełną konfigurację agenta (instructions + tools JSON)
    gotową do wklejenia w platform.openai.com/agent-builder.
    """
    from src.integrations.openai_agent import export_agent_config
    return export_agent_config()

