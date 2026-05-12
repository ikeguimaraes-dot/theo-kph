import os
import re
from supabase import create_client, Client

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]
        _client = create_client(url, key)
    return _client


def identificar_colaborador(telefone: str) -> dict | None:
    """Busca colaborador ativo pelo telefone. Testa com e sem prefixo whatsapp:."""
    db = _get_client()
    telefone_limpo = re.sub(r'[\s\-\(\)]', '', telefone)
    telefone_limpo = telefone_limpo.replace('whatsapp:', '')

    res = (
        db.table("employees")
        .select("id, nome, sobrenome, funcao, unit_id, units(name)")
        .or_(f"telefone.eq.{telefone_limpo},telefone.eq.whatsapp:{telefone_limpo}")
        .eq("ativo", True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    unidade = (row.get("units") or {}).get("name", "")
    return {
        "id": row["id"],
        "nome": row["nome"],
        "sobrenome": row.get("sobrenome", ""),
        "funcao": row.get("funcao", ""),
        "unidade": unidade,
    }


def buscar_holerites(employee_id: str) -> list[dict]:
    """Retorna os últimos 6 holerites do colaborador."""
    db = _get_client()
    res = (
        db.table("payslips")
        .select("competencia, salario_base, liquido, status, pdf_url")
        .eq("employee_id", employee_id)
        .order("competencia", desc=True)
        .limit(6)
        .execute()
    )
    return res.data or []


def buscar_banco_horas(employee_id: str) -> list[dict]:
    """Retorna os últimos 3 períodos de banco de horas."""
    db = _get_client()
    res = (
        db.table("time_records")
        .select(
            "periodo, horas_trabalhadas, horas_previstas, "
            "banco_horas_positivo, banco_horas_negativo, saldo_banco"
        )
        .eq("employee_id", employee_id)
        .order("periodo", desc=True)
        .limit(3)
        .execute()
    )
    return res.data or []


def buscar_ferias(employee_id: str) -> list[dict]:
    """Retorna histórico de férias do colaborador."""
    db = _get_client()
    res = (
        db.table("vacations")
        .select(
            "start_date, end_date, days_taken, days_entitled, "
            "acquisitive_period_start, acquisitive_period_end, status"
        )
        .eq("employee_id", employee_id)
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )
    return res.data or []


def registrar_falta(
    employee_id: str,
    data: str,
    tipo: str,
    motivo: str,
) -> str:
    """Registra falta em absences. Retorna o ID gerado."""
    score_map = {
        "Injustificada": -5,
        "Justificada": -2,
        "Atestado Médico": 0,
        "Atestado Acidente": 0,
        "Licença": 0,
    }
    score_impact = score_map.get(tipo, 0)

    db = _get_client()
    res = (
        db.table("absences")
        .insert(
            {
                "employee_id": employee_id,
                "data": data,
                "tipo": tipo,
                "motivo": motivo,
                "score_impact": score_impact,
            }
        )
        .execute()
    )
    row = res.data[0] if res.data else {}
    return row.get("id", "registrado")


def abrir_ticket(employee_id: str, categoria: str, descricao: str) -> str:
    """Abre ticket em theo_tickets. Retorna o ticket_id."""
    db = _get_client()
    res = (
        db.table("theo_tickets")
        .insert(
            {
                "employee_id": employee_id,
                "categoria": categoria,
                "descricao": descricao,
                "status": "aberto",
            }
        )
        .execute()
    )
    row = res.data[0] if res.data else {}
    return row.get("id", "aberto")


def save_metric(data: dict) -> None:
    try:
        _get_client().table("agent_metrics").insert(data).execute()
    except Exception as exc:
        import logging
        logging.getLogger("theo.metrics").warning("Falha ao salvar métrica: %s", exc)
