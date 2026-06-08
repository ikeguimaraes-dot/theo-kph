import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from twilio.rest import Client as TwilioClient
from twilio.twiml.messaging_response import MessagingResponse

import claude_client
import conversation
import instrumentation
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
    yield
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


class SendRequest(BaseModel):
    phone: str
    message: str
    operator_name: str = "Operador"


class SendResponse(BaseModel):
    ok: bool
    error: str | None = None


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "theo"}


@app.post("/send", response_model=SendResponse)
async def send_operator(req: SendRequest):
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
async def chat(req: ChatRequest):
    """Endpoint web para o KPH-OS."""
    session_key = f"web:{req.session_id}"
    log.info("Chat web [%s]: %s", session_key, req.message[:80])

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
            log.info("Colaborador identificado: %s (%s)", nome_completo, req.employee_id)
        else:
            log.warning("employee_id %s não encontrado no banco", req.employee_id)

    t0 = time.perf_counter()
    response_text, usage = claude_client.process_message(session_key, history, req.message, employee_context)
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
    telefone: str = form.get("From", "")
    body: str = form.get("Body", "").strip()

    log.info("Mensagem de %s: %s", telefone, body[:80])

    if not telefone or not body:
        resp = MessagingResponse()
        resp.message("Não recebi sua mensagem. Pode tentar de novo?")
        return Response(content=str(resp), media_type="application/xml")

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
    asyncio.get_event_loop().run_in_executor(
        None, db.save_metric, {"agent": "theo", **metric}
    )

    resp = MessagingResponse()
    resp.message(response_text)
    return Response(content=str(resp), media_type="application/xml")
