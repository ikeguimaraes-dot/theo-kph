import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from twilio.twiml.messaging_response import MessagingResponse

import claude_client
import conversation
import instrumentation
import supabase_client as db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("theo")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Theo iniciando...")
    yield
    log.info("Theo encerrando.")


app = FastAPI(title="Theo — Agente SAC Interno KPH", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "theo"}


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
