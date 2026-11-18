import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from twilio.rest import Client as TwilioClient
from twilio.twiml.messaging_response import MessagingResponse

import claude_client
import conversation
import instrumentation
import security
import pipou_sync
import supabase_client as db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("theo")

AGENT_NAME = "theo"
TWILIO_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

_twilio: TwilioClient | None = None


def get_twilio() -> TwilioClient:
    global _twilio
    if _twilio is None:
        _twilio = TwilioClient(
            os.environ["TWILIO_ACCOUNT_SID"],
            os.environ["TWILIO_AUTH_TOKEN"],
        )
    return _twilio


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Theo iniciando...")
    sync_task=asyncio.create_task(pipou_sync.run())
    try:
        yield
    finally:
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass
    log.info("Theo encerrando.")


app = FastAPI(title="Theo — Agente SAC Interno KPH", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://kph-os.vercel.app",
        "https://kph-os-pessoas.vercel.app",
        "http://localhost:3000",
        "http://localhost:3002",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    employee_id: str | None = None   # opcional: passar o UUID do colaborador logado


class ChatResponse(BaseModel):
    reply: str
    session_id: str


class MobileChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class MobileReportRequest(BaseModel):
    content: str = Field(min_length=1, max_length=12000)


@app.post('/mobile/report')
async def mobile_report(req: MobileReportRequest, request: Request):
    employee_id = await security.require_employee_session(request)
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail='Informe a resposta a denunciar.')
    # Reuse the existing support queue. Never ask the model to process a report
    # or accept an employee_id supplied in the request body.
    try:
        ticket_id = await asyncio.to_thread(
            db.abrir_ticket, employee_id, 'caso_sensivel',
            'Denúncia de resposta do Theo pelo Pipou:\n\n' + content)
        if not ticket_id or ticket_id == 'aberto':
            raise ValueError('No persisted ticket identifier')
    except Exception:
        log.warning('Falha ao registrar denúncia do Theo')
        raise HTTPException(status_code=503, detail='Não foi possível registrar a denúncia.')
    return {'id': str(ticket_id), 'status': 'recebida'}


@app.post('/mobile/chat', response_model=ChatResponse)
async def mobile_chat(req: MobileChatRequest, request: Request):
    employee_id = await security.require_employee_session(request)
    # Session and identity are server-derived. The caller cannot select another
    # employee or another conversation by editing JSON fields.
    return await respond_chat(ChatRequest(session_id='hos_' + employee_id,
                                         message=req.message, employee_id=employee_id),
                              authorized_employee_id=employee_id)


class SendRequest(BaseModel):
    phone: str
    message: str
    operator_name: str = "Operador"


class SendResponse(BaseModel):
    ok: bool
    error: str | None = None


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "theo", "people_project":
            (os.environ.get("SUPABASE_URL", "") if os.environ.get("PIPOU_LEGACY_RH_MODE")=="true" else os.environ.get("PIPOU_SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))).split("//")[-1].split(".")[0],
            "legacy_sync": os.environ.get("PIPOU_SYNC_ENABLED")=="true"}


@app.post("/send", response_model=SendResponse)
async def send_operator(req: SendRequest, request: Request):
    security.require_api_key(request, AGENT_NAME)
    """Operador injeta mensagem — salva no histórico e envia via Twilio WhatsApp."""
    phone = req.phone.replace("whatsapp:", "").strip()
    wa_to = f"whatsapp:{phone}"

    # 1. Registra no histórico como "operator"
    conversation.append_message(phone, "operator", req.message)

    # 2. Marca conversa como assumida + seta operador
    try:
        db.get_client().table("agent_conversations").update({
            "status": "assumida",
            "operator_name": req.operator_name,
        }).eq("agent", AGENT_NAME).eq("phone", phone).execute()
    except Exception as e:
        log.error("Supabase update failed: %s", e)

    # 3. Envia via Twilio
    try:
        get_twilio().messages.create(
            from_=TWILIO_FROM,
            to=wa_to,
            body=req.message,
        )
        log.info("Twilio enviado para %s por %s", phone, req.operator_name)
    except Exception as e:
        log.error("Twilio send failed para %s: %s", phone, e)
        return SendResponse(ok=False, error=str(e))

    return SendResponse(ok=True)


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    security.require_api_key(request, AGENT_NAME)
    return await respond_chat(req)


async def respond_chat(req: ChatRequest, authorized_employee_id: str | None = None):
    """Endpoint web para o KPH-OS."""
    session_key = f"web:{req.session_id}"
    log.info("Chat request received")

    history = conversation.get_history(session_key)

    # Injeta contexto estruturado do colaborador logado no system prompt
    employee_context = ""
    if req.employee_id:
        colaborador = db.identificar_por_id(req.employee_id)
        if colaborador:
            nome_completo = colaborador["nome"]
            if colaborador.get("sobrenome"):
                nome_completo += f" {colaborador['sobrenome']}"
            employee_context = (
                f"Você está conversando com {nome_completo}, "
                f"cargo: {colaborador.get('funcao') or 'não informado'}, "
                f"departamento: {colaborador.get('departamento') or 'não informado'}, "
                f"unidade: {colaborador.get('unidade') or 'não informada'}. "
                f"employee_id: {colaborador['id']}. "
                f"Use esse employee_id nas tools quando precisar buscar dados deste colaborador."
            )
            log.info("Colaborador identificado")
        else:
            log.warning("employee_id %s não encontrado no banco", req.employee_id)

    t0 = time.perf_counter()
    response_text, usage = claude_client.process_message(session_key, history, req.message, employee_context, authorized_employee_id=authorized_employee_id)
    latency_ms = (time.perf_counter() - t0) * 1000

    conversation.append_message(session_key, "user", req.message)
    conversation.append_message(session_key, "assistant", response_text)

    intencao = instrumentation.detectar_intencao(req.message)
    metric = instrumentation.log_turn(
        phone=session_key,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        latency_ms=latency_ms,
        intencao=intencao,
    )
    asyncio.create_task(
        asyncio.to_thread(db.save_metric, {"agent": "theo", **metric})
    )

    return ChatResponse(reply=response_text, session_id=req.session_id)


@app.post("/webhook")
async def webhook(request: Request):
    form = await request.form()
    security.validate_twilio(request, form)
    telefone: str = form.get("From", "")
    body: str = form.get("Body", "").strip()

    log.info("Mensagem de %s: %s", telefone, body[:80])

    if not telefone or not body:
        resp = MessagingResponse()
        
        return Response(content=str(resp), media_type="application/xml")

    if not security.claim_message(db.get_client(), AGENT_NAME, form):
        return Response(content=str(MessagingResponse()), media_type="application/xml")
    if security.is_assumed(db.get_client(), AGENT_NAME, telefone):
        conversation.append_message(telefone, "user", body)
        return Response(content=str(MessagingResponse()), media_type="application/xml")

    history = conversation.get_history(telefone)

    t0 = time.perf_counter()
    response_text, usage = claude_client.process_message(telefone, history, body)
    latency_ms = (time.perf_counter() - t0) * 1000

    conversation.append_message(telefone, "user", body)
    conversation.append_message(telefone, "assistant", response_text)

    intencao = instrumentation.detectar_intencao(body)
    metric = instrumentation.log_turn(
        phone=telefone,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        latency_ms=latency_ms,
        intencao=intencao,
    )
    asyncio.create_task(
        asyncio.to_thread(db.save_metric, {"agent": "theo", **metric})
    )

    resp = MessagingResponse()
    if not security.is_assumed(db.get_client(), AGENT_NAME, telefone):
        resp.message(response_text)
    return Response(content=str(resp), media_type="application/xml")

