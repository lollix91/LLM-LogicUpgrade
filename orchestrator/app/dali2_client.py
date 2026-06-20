import os
import httpx

DALI2_URL = os.getenv("DALI2_URL", "http://localhost:8080")


async def inject_event(agent: str, event: str) -> dict:
    """Inject an event into a DALI2 agent."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{DALI2_URL}/api/inject",
            json={"agent": agent, "event": event},
        )
        response.raise_for_status()
        return response.json()


async def send_message(to: str, content: str) -> dict:
    """Send a message to a DALI2 agent."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{DALI2_URL}/api/send",
            json={"to": to, "content": content},
        )
        response.raise_for_status()
        return response.json()


async def get_beliefs(agent: str) -> list[str]:
    """Get beliefs of a DALI2 agent."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{DALI2_URL}/api/beliefs",
            params={"agent": agent},
        )
        response.raise_for_status()
        data = response.json()
        return data.get("beliefs", [])


async def get_logs(agent: str, since: float = 0) -> list[dict]:
    """Get logs from a DALI2 agent."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{DALI2_URL}/api/logs",
            params={"agent": agent, "since": since},
        )
        response.raise_for_status()
        return response.json().get("logs", [])


async def get_agents() -> list[dict]:
    """List DALI2 agents."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{DALI2_URL}/api/agents")
        response.raise_for_status()
        return response.json().get("agents", [])


async def reload_agents(file: str = "examples/logic_solver.pl") -> dict:
    """Reload DALI2 agent file."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{DALI2_URL}/api/reload",
            json={"file": file},
        )
        response.raise_for_status()
        return response.json()
