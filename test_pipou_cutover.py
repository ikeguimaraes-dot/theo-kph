import asyncio
from unittest.mock import AsyncMock,Mock
import pytest
from fastapi import HTTPException
import httpx
import security
import supabase_client as db
from test_security import request
EID='00000000-0000-4000-8000-000000000001'
NEW='https://nasvczssqtuasudpvkum.supabase.co'
OLD='https://iqgrvptrtphvbmvrqntm.supabase.co'
def setup(monkeypatch,responses):
    monkeypatch.setenv('PIPOU_SUPABASE_URL',NEW);monkeypatch.setenv('PIPOU_SUPABASE_SERVICE_KEY','eyJnew-test')
    monkeypatch.setenv('SUPABASE_URL',OLD);monkeypatch.setenv('SUPABASE_SERVICE_KEY','sb_secret_test')
    client=AsyncMock();client.post.side_effect=responses
    ctx=AsyncMock();ctx.__aenter__.return_value=client
    monkeypatch.setattr(security.httpx,'AsyncClient',Mock(return_value=ctx))
    return client
def resp(code,data):
    r=Mock(status_code=code,is_success=200<=code<300);r.json.return_value=data;return r
def call():return asyncio.run(security.require_employee_session(request({'X-Employee-Session':'a'*64})))
def test_new_session_does_not_query_legacy(monkeypatch):
    client=setup(monkeypatch,[resp(200,{'employee_id':EID})]);assert call()==EID
    assert client.post.call_count==1 and client.post.call_args.args[0].startswith(NEW)
def test_legacy_session_must_still_match_new_credential(monkeypatch):
    client=setup(monkeypatch,[resp(401,{}),resp(200,{'employee_id':EID,'credential_fingerprint':'b'*64}),resp(200,True)])
    assert call()==EID;assert client.post.call_count==3
    assert client.post.call_args.args[0]==NEW+'/rest/v1/rpc/employee_legacy_identity_check'
    assert client.post.call_args.kwargs['json']['p_employee_id']==EID
@pytest.mark.parametrize('response',[resp(503,{}),httpx.ConnectError('offline')])
def test_new_database_failure_never_falls_back(monkeypatch,response):
    client=setup(monkeypatch,[response])
    with pytest.raises(HTTPException) as e:call()
    assert e.value.status_code==503 and client.post.call_count==1
def test_revoked_new_identity_cannot_use_legacy_session(monkeypatch):
    setup(monkeypatch,[resp(401,{}),resp(200,{'employee_id':EID,'credential_fingerprint':'b'*64}),resp(200,False)])
    with pytest.raises(HTTPException) as e:call()
    assert e.value.status_code==401
def test_unexpected_target_fails_closed(monkeypatch):
    client=setup(monkeypatch,[]);monkeypatch.setenv('PIPOU_SUPABASE_URL','https://example.invalid')
    with pytest.raises(HTTPException) as e:call()
    assert e.value.status_code==503;client.post.assert_not_called()
def test_rh_client_is_separate_from_shared_agent_client(monkeypatch):
    monkeypatch.setenv('PIPOU_SUPABASE_URL',NEW);monkeypatch.setenv('PIPOU_SUPABASE_SERVICE_KEY','new-server-test')
    monkeypatch.setenv('SUPABASE_URL',OLD);monkeypatch.setenv('SUPABASE_SERVICE_KEY','old-server-test')
    monkeypatch.setattr(db,'_people_client',None);monkeypatch.setattr(db,'_client',None)
    factory=Mock(side_effect=[object(),object()]);monkeypatch.setattr(db,'create_client',factory)
    assert db.get_people_client() is not db.get_client()
    assert factory.call_args_list[0].args==(NEW,'new-server-test')
    assert factory.call_args_list[1].args==(OLD,'old-server-test')


def test_legacy_customer_mode_keeps_rh_in_customer_database_and_bridge_separate(monkeypatch):
    monkeypatch.setenv('PIPOU_LEGACY_RH_MODE','true')
    old=object();new=object()
    monkeypatch.setattr(db,'get_client',Mock(return_value=old))
    monkeypatch.setattr(db,'get_pipou_client',Mock(return_value=new))
    assert db.get_people_client() is old
    assert db.get_pipou_client() is new

def test_legacy_customer_mode_never_validates_new_product_sessions(monkeypatch):
    client=setup(monkeypatch,[resp(200,{'employee_id':EID})]);monkeypatch.setenv('PIPOU_LEGACY_RH_MODE','true')
    assert call()==EID
    assert client.post.call_count==1
    assert client.post.call_args.args[0].startswith(OLD)
