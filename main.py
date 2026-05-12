import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from twilio.twiml.messaging_response import MessagingResponse

import claude_client
import conversation

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

    response_text = claude_client.process_message(telefone, history, body)

    conversation.append_message(telefone, "user", body)
    conversation.append_message(telefone, "assistant", response_text)

    resp = MessagingResponse()
    resp.message(response_text)
    return Response(content=str(resp), media_type="application/xml")
