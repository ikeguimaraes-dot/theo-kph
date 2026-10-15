import os
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.datastructures import FormData
from twilio.request_validator import RequestValidator
import security

def request(headers):
    return Request({"type":"http","method":"POST","scheme":"https","server":("bot.test",443),"path":"/webhook","query_string":b"","headers":[(k.lower().encode(),v.encode()) for k,v in headers.items()]})

def test_no_key_denies(monkeypatch):
    monkeypatch.setenv("THEO_INTERNAL_TOKEN", "test-secret")
    with pytest.raises(HTTPException) as e: security.require_api_key(request({}), "theo")
    assert e.value.status_code == 401

def test_correct_key(monkeypatch):
    monkeypatch.setenv("THEO_INTERNAL_TOKEN", "test-secret")
    security.require_api_key(request({"X-API-Key":"test-secret"}), "theo")

def test_signature(monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-only-token")
    monkeypatch.setenv("TWILIO_WEBHOOK_URL", "https://bot.test/webhook")
    form=FormData({"From":"whatsapp:+10000000000","Body":"test","MessageSid":"SM"+"a"*32})
    signature=RequestValidator("test-only-token").compute_signature("https://bot.test/webhook", form)
    security.validate_twilio(request({"X-Twilio-Signature":signature}), form)
    with pytest.raises(HTTPException) as e: security.validate_twilio(request({"X-Twilio-Signature":"invalid"}),form)
    assert e.value.status_code == 403

def test_dedupe_only_conflicts_are_duplicates():
    client=Mock(); form=FormData({"MessageSid":"SM"+"a"*32})
    assert security.claim_message(client,"theo",form)
    err=Exception("duplicate");err.code="23505"
    client.table.return_value.insert.return_value.execute.side_effect=err
    assert not security.claim_message(client,"theo",form)
    client.table.return_value.insert.return_value.execute.side_effect=Exception("offline")
    with pytest.raises(HTTPException) as e: security.claim_message(client,"theo",form)
    assert e.value.status_code==503

def test_takeover_blocks():
    client=Mock();client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data=[{"status":"assumida"}]
    assert security.is_assumed(client,"theo","whatsapp:+10000000000")

def test_http_auth_boundaries(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY','test-only')
    monkeypatch.setenv('TWILIO_AUTH_TOKEN','test-only-token')
    monkeypatch.setenv('TWILIO_WEBHOOK_URL','https://bot.test/webhook')
    monkeypatch.setenv('THEO_INTERNAL_TOKEN','test-secret')
    from fastapi.testclient import TestClient
    import main
    provider=Mock(side_effect=AssertionError('provider must not run'))
    monkeypatch.setattr(main.claude_client,'process_message',provider)
    client=TestClient(main.app,base_url='https://bot.test')
    assert client.post('/webhook',data={},headers={'X-Twilio-Signature':'invalid'}).status_code==403
    signature=RequestValidator('test-only-token').compute_signature('https://bot.test/webhook',{})
    assert client.post('/webhook',data={},headers={'X-Twilio-Signature':signature}).status_code==200
    assert client.post('/send',json={'phone':'+10000000000','message':'test'}).status_code==401
    assert client.post('/chat',json={'session_id':'test','message':'test'}).status_code==401
    provider.assert_not_called()
