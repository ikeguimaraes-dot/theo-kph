THEO_TOOLS = [
    {
        "name": "identificar_colaborador",
        "description": (
            "Identifica o colaborador pelo número de telefone. "
            "Chamar SEMPRE no início da conversa para personalizar o atendimento."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "telefone": {
                    "type": "string",
                    "description": "Número de telefone no formato Twilio: 'whatsapp:+55...' ou somente '+55...'",
                },
            },
            "required": ["telefone"],
        },
    },
    {
        "name": "buscar_holerites",
        "description": "Retorna os últimos 6 holerites do colaborador (competência, salário base, líquido, status, link PDF).",
        "input_schema": {
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "UUID do colaborador obtido via identificar_colaborador.",
                },
            },
            "required": ["employee_id"],
        },
    },
    {
        "name": "buscar_banco_horas",
        "description": "Retorna os últimos 3 períodos de banco de horas do colaborador (saldo, horas trabalhadas, horas previstas).",
        "input_schema": {
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "UUID do colaborador.",
                },
            },
            "required": ["employee_id"],
        },
    },
    {
        "name": "buscar_ferias",
        "description": "Retorna histórico e saldo de férias do colaborador (datas, dias utilizados, dias devidos, período aquisitivo, status).",
        "input_schema": {
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "UUID do colaborador.",
                },
            },
            "required": ["employee_id"],
        },
    },
    {
        "name": "registrar_falta",
        "description": "Registra uma falta do colaborador no banco de dados.",
        "input_schema": {
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "UUID do colaborador.",
                },
                "data": {
                    "type": "string",
                    "description": "Data da falta no formato YYYY-MM-DD.",
                },
                "tipo": {
                    "type": "string",
                    "enum": [
                        "Injustificada",
                        "Justificada",
                        "Atestado Médico",
                        "Atestado Acidente",
                        "Licença",
                    ],
                    "description": "Tipo da falta.",
                },
                "motivo": {
                    "type": "string",
                    "description": "Descrição do motivo informado pelo colaborador.",
                },
            },
            "required": ["employee_id", "data", "tipo", "motivo"],
        },
    },
    {
        "name": "abrir_ticket",
        "description": "Abre um ticket de atendimento para casos que requerem encaminhamento ou acompanhamento.",
        "input_schema": {
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "UUID do colaborador.",
                },
                "categoria": {
                    "type": "string",
                    "enum": [
                        "beneficios",
                        "folha_pagamento",
                        "ferias_afastamento",
                        "admissao",
                        "desligamento",
                        "politicas_internas",
                        "suporte_lideranca",
                        "caso_sensivel",
                    ],
                    "description": "Categoria do ticket.",
                },
                "descricao": {
                    "type": "string",
                    "description": "Descrição completa do caso para registro interno.",
                },
            },
            "required": ["employee_id", "categoria", "descricao"],
        },
    },
]
