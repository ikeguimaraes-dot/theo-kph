import httpx

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


async def send_push_notification(
    token: str,
    title: str,
    body: str,
    data: dict = {}
):
    payload = {
        "to": token,
        "title": title,
        "body": body,
        "data": data,
        "sound": "default",
        "priority": "high",
        "channelId": "default",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(EXPO_PUSH_URL, json=payload)
        return response.json()


async def notify_ponto_nao_batido(token: str, nome: str):
    return await send_push_notification(
        token=token,
        title="⏰ Ponto não registrado",
        body=f"{nome}, você ainda não registrou sua entrada hoje.",
        data={"type": "ponto_nao_batido"},
    )


async def notify_aprovacao_pendente(token: str, nome_colaborador: str):
    return await send_push_notification(
        token=token,
        title="📋 Aprovação pendente",
        body=f"{nome_colaborador} tem um ponto fora do raio aguardando aprovação.",
        data={"type": "aprovacao_pendente"},
    )


async def notify_ajuste_resolvido(token: str, status: str, data_ref: str):
    emoji = "✅" if status == "aprovado" else "❌"
    texto = "aprovado" if status == "aprovado" else "rejeitado"
    return await send_push_notification(
        token=token,
        title=f"{emoji} Ajuste de ponto {texto}",
        body=f"Seu ajuste de {data_ref} foi {texto} pelo gestor.",
        data={"type": "ajuste_resolvido", "status": status},
    )


async def notify_campanha_nova(token: str, titulo_campanha: str):
    return await send_push_notification(
        token=token,
        title="📢 Nova campanha",
        body=titulo_campanha,
        data={"type": "campanha_nova"},
    )
