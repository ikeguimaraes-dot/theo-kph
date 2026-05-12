import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger("theo.metrics")

COST_INPUT_PER_M = 3.0   # USD por milhão de tokens — claude-sonnet-4-6
COST_OUTPUT_PER_M = 15.0

_INTENT_KEYWORDS = [
    ("holerite",      ["holerite", "salário", "salario", "contracheque", "pagamento", "liquido", "líquido"]),
    ("banco_horas",   ["banco de horas", "banco horas", "hora extra", "horas extras", "saldo de horas"]),
    ("ferias",        ["férias", "ferias", "descanso", "periodo aquisitivo"]),
    ("falta",         ["falta", "faltei", "ausência", "ausencia", "atestado", "licença", "licenca"]),
    ("ticket",        ["ticket", "problema", "reclamação", "reclamacao", "dúvida", "duvida", "solicitação", "solicitacao"]),
    ("identificacao", ["meu nome", "sou o", "sou a", "me identificar", "cadastrar"]),
    ("saudacao",      ["oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "tudo bem"]),
]


def detectar_intencao(texto: str) -> str:
    t = texto.lower()
    for label, keywords in _INTENT_KEYWORDS:
        if any(k in t for k in keywords):
            return label
    return "outros"


def log_turn(
    phone: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    intencao: str = "",
) -> dict:
    cost = (input_tokens * COST_INPUT_PER_M + output_tokens * COST_OUTPUT_PER_M) / 1_000_000
    logger.info(
        "[turn] phone=%s in=%d out=%d cost=$%.5f latency=%.0fms intencao=%r",
        phone[-4:], input_tokens, output_tokens, cost, latency_ms, intencao,
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
        "latency_ms": round(latency_ms),
        "intencao": intencao,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
