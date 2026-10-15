"""Fail-closed inbound authentication and durable Twilio deduplication."""
import hashlib
import hmac
import os
import re
from fastapi import HTTPException, Request
from twilio.request_validator import RequestValidator

def require_api_key(request: Request, agent: str) -> None:
    expected = os.environ.get(f"{agent.upper()}_INTERNAL_TOKEN", "")
    supplied = request.headers.get("X-API-Key", "")
    if not expected:
        raise HTTPException(503, "Internal authentication is not configured")
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "Unauthorized")

def validate_twilio(request: Request, form) -> None:
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        raise HTTPException(403, "Invalid Twilio signature")
    url = os.environ.get("TWILIO_WEBHOOK_URL", "")
    if not token or not url:
        raise HTTPException(503, "Webhook authentication is not configured")
    if not RequestValidator(token).validate(url, form, signature):
        raise HTTPException(403, "Invalid Twilio signature")

def claim_message(client, agent: str, form) -> bool:
    sid = str(form.get("MessageSid", ""))
    if not re.fullmatch(r"SM[0-9a-fA-F]{32}", sid):
        raise HTTPException(400, "MessageSid required")
    org = os.environ.get("KPH_ORG_ID", "00000000-0000-0000-0000-000000000001")
    # Unique key is the claim. Never retry an uncertain inference automatically.
    try:
        client.table("ai1_bot_webhook_receipts").insert({
            "org_id": org, "agent": agent, "message_sid": sid,
            "payload_hash": hashlib.sha256(str(sorted(form.multi_items())).encode()).hexdigest(),
        }).execute()
        return True
    except Exception as error:
        if getattr(error, "code", None) == "23505":
            return False
        raise HTTPException(503, "Webhook receipt unavailable") from error

def is_assumed(client, agent: str, phone: str) -> bool:
    result = client.table("agent_conversations").select("status").eq("agent", agent).eq("phone", phone.replace("whatsapp:", "").strip()).limit(1).execute()
    return bool(result.data and result.data[0].get("status") == "assumida")
