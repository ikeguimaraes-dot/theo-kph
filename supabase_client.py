import os
import re
from supabase import create_client, Client

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]
        _client = create_client(url, key)
    return _client


def identificar_colaborador(telefone: str) -> dict | None:
    """
    Busca colaborador ativo pelo telefone.
    Normaliza para canônico BR (só dígitos, sem DDI 55) — espelha norm_fone_br()
    do banco e normalizarTelefone() do front-end — e consulta contatos_kph como
    fonte única, evitando .or_() com '+' em PostgREST.
    """
    digits = re.sub(r'[^\d]', '', telefone)
    if len(digits) in (12, 13) and digits.startswith('55'):
        digits = digits[2:]
    canonical = digits  # ex: "11969498225"

    if not canonical:
        return None

    db = get_client()
    res = (
        db.table("contatos_kph")
        .select("employee_id")
        .eq("telefone", canonical)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    employee_id = res.data[0].get("employee_id")
    if not employee_id:
        return None
    return identificar_por_id(employee_id)


def identificar_por_id(employee_id: str) -> dict | None:
    """Busca colaborador ativo pelo UUID. Usado pelo /chat do HOS App."""
    db = get_client()
    try:
        res = (
            db.table("employees")
            .select("id, nome, sobrenome, funcao, departamento, unit_id, telefone, units(name)")
            .eq("id", employee_id)
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
            "departamento": row.get("departamento", ""),
            "unidade": unidade,
            "telefone": row.get("telefone", ""),
        }
    except Exception as exc:
        import logging
        logging.getLogger("theo").warning("[THEO] identificar_por_id error: %s", exc)
        return None


def buscar_holerites(employee_id: str) -> list[dict]:
    """Retorna os últimos 6 holerites do colaborador."""
    db = get_client()
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
    db = get_client()
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
    db = get_client()
    res = (
        db.table("vacations")
        .select(
            "inicio_gozo, fim_gozo, dias_gozados, dias_direito, "
            "periodo_aquisitivo_inicio, periodo_aquisitivo_fim, status"
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

    db = get_client()
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
    db = get_client()
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
        row = {k: v for k, v in data.items() if k != "timestamp"}
        get_client().table("agent_metrics").insert(row).execute()
    except Exception as exc:
        import logging
        logging.getLogger("theo.metrics").error("Falha ao salvar métrica: %s", exc)
