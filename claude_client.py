import json
import os
import anthropic
from tools import THEO_TOOLS
import supabase_client as db

MODEL = "claude-sonnet-4-6"
MAX_TOOL_ITERATIONS = 8

SYSTEM_PROMPT = open(
    os.path.join(os.path.dirname(__file__), "system_prompt.txt"),
    encoding="utf-8",
).read()

_anthropic = anthropic.Anthropic()


def _execute_tool(name: str, input_data: dict) -> str:
    try:
        if name == "identificar_colaborador":
            colaborador = db.identificar_colaborador(input_data["telefone"])
            if not colaborador:
                return "Colaborador não encontrado no banco. Solicite nome e unidade para registro manual."
            return json.dumps(colaborador, ensure_ascii=False)

        elif name == "buscar_holerites":
            holerites = db.buscar_holerites(input_data["employee_id"])
            if not holerites:
                return "Nenhum holerite encontrado para este colaborador."
            return json.dumps(holerites, ensure_ascii=False, default=str)

        elif name == "buscar_banco_horas":
            registros = db.buscar_banco_horas(input_data["employee_id"])
            if not registros:
                return "Nenhum registro de banco de horas encontrado."
            return json.dumps(registros, ensure_ascii=False, default=str)

        elif name == "buscar_ferias":
            ferias = db.buscar_ferias(input_data["employee_id"])
            if not ferias:
                return "Nenhum registro de férias encontrado."
            return json.dumps(ferias, ensure_ascii=False, default=str)

        elif name == "registrar_falta":
            absence_id = db.registrar_falta(
                employee_id=input_data["employee_id"],
                data=input_data["data"],
                tipo=input_data["tipo"],
                motivo=input_data["motivo"],
            )
            return json.dumps({"absence_id": absence_id, "status": "registrado"})

        elif name == "abrir_ticket":
            ticket_id = db.abrir_ticket(
                employee_id=input_data["employee_id"],
                categoria=input_data["categoria"],
                descricao=input_data["descricao"],
            )
            return json.dumps({"ticket_id": ticket_id, "status": "aberto"})

        else:
            return f"Tool '{name}' não reconhecida."

    except Exception as exc:
        return f"Erro ao executar {name}: {exc}"


def process_message(telefone: str, history: list[dict], user_text: str) -> str:
    messages = list(history)
    messages.append({"role": "user", "content": user_text})

    for _ in range(MAX_TOOL_ITERATIONS):
        response = _anthropic.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=THEO_TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "type") and block.type == "text":
                    return block.text
            return "Pode me falar mais sobre sua dúvida?"

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    result = _execute_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )
            messages.append({"role": "user", "content": tool_results})
            continue

        break

    for block in (response.content if response else []):
        if hasattr(block, "type") and block.type == "text":
            return block.text
    return "Desculpe, tive um problema interno. Pode repetir?"
