"""
Persistent conversation history via Supabase (agent_conversations table).
Falls back to empty list if the row doesn't exist or last activity > 24h.
"""

from datetime import datetime, timezone, timedelta
from supabase_client import get_client

AGENT = "theo"
MAX_MESSAGES = 20
SESSION_TTL_HOURS = 24


def _clean_phone(telefone: str) -> str:
    return telefone.replace("whatsapp:", "").strip()


def get_history(telefone: str) -> list[dict]:
    phone = _clean_phone(telefone)
    sb = get_client()
    response = (
        sb.table("agent_conversations")
        .select("messages, last_activity")
        .eq("agent", AGENT)
        .eq("phone", phone)
        .limit(1)
        .execute()
    )
    if not response.data:
        return []

    row = response.data[0]
    last_activity = datetime.fromisoformat(row["last_activity"])
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) - last_activity > timedelta(hours=SESSION_TTL_HOURS):
        clear_history(telefone)
        return []

    return list(row["messages"] or [])


def append_message(telefone: str, role: str, content) -> None:
    phone = _clean_phone(telefone)
    sb = get_client()

    # Fetch current messages
    response = (
        sb.table("agent_conversations")
        .select("messages")
        .eq("agent", AGENT)
        .eq("phone", phone)
        .limit(1)
        .execute()
    )
    messages = list(response.data[0]["messages"] or []) if response.data else []

    messages.append({"role": role, "content": content})
    if len(messages) > MAX_MESSAGES:
        messages = messages[-MAX_MESSAGES:]

    sb.table("agent_conversations").upsert(
        {
            "agent": AGENT,
            "phone": phone,
            "messages": messages,
            "last_activity": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="agent,phone",
    ).execute()


def clear_history(telefone: str) -> None:
    phone = _clean_phone(telefone)
    sb = get_client()
    sb.table("agent_conversations").delete().eq("agent", AGENT).eq("phone", phone).execute()
