import os
from unittest.mock import Mock, AsyncMock
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
os.environ.setdefault('ANTHROPIC_API_KEY', 'test-only')
import main
import security
import claude_client

EMPLOYEE_A = '00000000-0000-4000-8000-000000000001'
EMPLOYEE_B = '00000000-0000-4000-8000-000000000002'


def test_mobile_does_not_call_provider_without_session(monkeypatch):
    provider = Mock(side_effect=AssertionError('provider must not run'))
    monkeypatch.setattr(main.claude_client, 'process_message', provider)
    client = TestClient(main.app)
    assert client.post('/mobile/chat', json={'message': 'test'}).status_code == 401
    assert client.post('/mobile/chat', json={'message': 'test'}, headers={'X-Employee-Session': 'invalid'}).status_code == 401
    provider.assert_not_called()


def test_mobile_ignores_forged_identity_and_history(monkeypatch):
    monkeypatch.setattr(security, 'require_employee_session', AsyncMock(return_value=EMPLOYEE_A))
    history = Mock(return_value=[])
    monkeypatch.setattr(main.conversation, 'get_history', history)
    monkeypatch.setattr(main.conversation, 'append_message', Mock())
    monkeypatch.setattr(main.db, 'identificar_por_id', Mock(return_value={'id': EMPLOYEE_A, 'nome': 'Teste'}))
    monkeypatch.setattr(main.instrumentation, 'log_turn', Mock(return_value={}))
    monkeypatch.setattr(main.db, 'save_metric', Mock())
    provider = Mock(return_value=('Resposta de teste', {'input_tokens': 0, 'output_tokens': 0}))
    monkeypatch.setattr(main.claude_client, 'process_message', provider)
    result = TestClient(main.app).post('/mobile/chat', json={'message': 'test', 'employee_id': EMPLOYEE_B, 'session_id': 'other-person'})
    assert result.status_code == 200
    assert result.json()['session_id'] == 'hos_' + EMPLOYEE_A
    history.assert_called_once_with('web:hos_' + EMPLOYEE_A)
    assert provider.call_args.kwargs['authorized_employee_id'] == EMPLOYEE_A


def test_mobile_tool_cannot_switch_employee(monkeypatch):
    query = Mock(side_effect=AssertionError('other employee must not be queried'))
    monkeypatch.setattr(claude_client.db, 'buscar_holerites', query)
    assert 'negado' in claude_client._execute_tool('buscar_holerites', {'employee_id': EMPLOYEE_B}, EMPLOYEE_A)
    query.assert_not_called()
    lookup = Mock(side_effect=AssertionError('phone lookup must not run'))
    monkeypatch.setattr(claude_client.db, 'identificar_colaborador', lookup)
    claude_client._execute_tool('identificar_colaborador', {'telefone': '+10000000000'}, EMPLOYEE_A)
    lookup.assert_not_called()


def test_mobile_own_tool_still_works(monkeypatch):
    query = Mock(return_value=[])
    monkeypatch.setattr(claude_client.db, 'buscar_holerites', query)
    claude_client._execute_tool('buscar_holerites', {'employee_id': EMPLOYEE_A}, EMPLOYEE_A)
    query.assert_called_once_with(EMPLOYEE_A)


def test_mobile_session_server_validation(monkeypatch):
    import asyncio
    import httpx
    monkeypatch.setenv('SUPABASE_URL', 'https://iqgrvptrtphvbmvrqntm.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'sb_secret_test_only')
    response = Mock(status_code=200, is_success=True)
    response.json.return_value = {'employee_id': EMPLOYEE_A}
    client = AsyncMock()
    client.post.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(security.httpx, 'AsyncClient', Mock(return_value=context))
    from test_security import request
    req = request({'X-Employee-Session': 'a' * 64})
    assert asyncio.run(security.require_employee_session(req)) == EMPLOYEE_A
    assert client.post.call_args.kwargs['headers']['X-Employee-Session'] == 'a' * 64
    assert 'Authorization' not in client.post.call_args.kwargs['headers']
    response.status_code = 401
    with pytest.raises(HTTPException) as error:
        asyncio.run(security.require_employee_session(req))
    assert error.value.status_code == 401
    client.post.side_effect = httpx.ConnectError('offline')
    with pytest.raises(HTTPException) as error:
        asyncio.run(security.require_employee_session(req))
    assert error.value.status_code == 503
