"""Fail-closed inbound authentication and durable Twilio deduplication."""
import hashlib
import hmac
import os
import re
from fastapi import HTTPException, Request
from twilio.request_validator import RequestValidator
import httpx
from uuid import UUID

async def require_employee_session(request: Request) -> str:
    token = request.headers.get('X-Employee-Session', '')
    if not re.fullmatch(r'[a-f0-9]{64}', token):
        raise HTTPException(401, 'Employee session required')
    primary_url = os.environ.get('PIPOU_SUPABASE_URL', '').rstrip('/')
    primary_key = os.environ.get('PIPOU_SUPABASE_SERVICE_KEY', '')
    legacy_url = os.environ.get('SUPABASE_URL', '').rstrip('/')
    legacy_key = os.environ.get('SUPABASE_SERVICE_KEY', '')
    if os.environ.get('PIPOU_LEGACY_RH_MODE')=='true':
        primary_url='';primary_key=''
    if not primary_url and not primary_key:
        candidates = [(legacy_url, legacy_key)]
    else:
        if primary_url != 'https://nasvczssqtuasudpvkum.supabase.co' or not primary_key:
            raise HTTPException(503, 'Employee authentication unavailable')
        candidates = [(primary_url, primary_key), (legacy_url, legacy_key)]
    for index, (url, key) in enumerate(candidates):
        if url not in ('https://nasvczssqtuasudpvkum.supabase.co', 'https://iqgrvptrtphvbmvrqntm.supabase.co') or not key:
            raise HTTPException(503, 'Employee authentication unavailable')
        headers = {'apikey': key, 'X-Hos-Protocol': '2', 'X-Employee-Session': token}
        if key.startswith('eyJ'):
            headers['Authorization'] = 'Bearer ' + key
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                result = await client.post(url + '/rest/v1/rpc/employee_session_check', headers=headers, json={})
            if result.status_code in (401, 403):
                if index + 1 < len(candidates):
                    continue
                raise HTTPException(401, 'Invalid or expired employee session')
            if not result.is_success:
                raise HTTPException(503, 'Employee authentication unavailable')
            identity = result.json()
            employee_id = str(UUID(identity['employee_id']))
            if index > 0:
                # A legacy session cannot re-enable someone whose RH access was
                # disabled, or whose credential changed, in the new project.
                fingerprint = identity.get('credential_fingerprint', '')
                if not re.fullmatch(r'[a-f0-9]{64}', fingerprint):
                    raise HTTPException(503, 'Employee authentication unavailable')
                async with httpx.AsyncClient(timeout=10) as client:
                    active = await client.post(primary_url + '/rest/v1/rpc/employee_legacy_identity_check',
                        headers={'apikey': primary_key, 'Authorization': 'Bearer ' + primary_key},
                        json={'p_employee_id': employee_id, 'p_fingerprint': fingerprint})
                if not active.is_success:
                    raise HTTPException(503, 'Employee authentication unavailable')
                if active.json() is not True:
                    raise HTTPException(401, 'Invalid or expired employee session')
            return employee_id
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Employee authentication unavailable')
    raise HTTPException(401, 'Invalid or expired employee session')

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
