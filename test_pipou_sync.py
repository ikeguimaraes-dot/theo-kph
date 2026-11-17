from unittest.mock import Mock
import hashlib
import pytest
import pipou_sync as sync

class Missing(Exception):
    status=404

def storage(client):
    bucket=Mock();client.storage.from_.return_value=bucket;return bucket

def event(op='INSERT'):
    return {'id':'e','operation':op,'schema_name':'storage','record_key':{'bucket_id':'employee-documents','name':'test/file.pdf'},'row_data':{'bucket_id':'employee-documents','name':'test/file.pdf','metadata':{'mimetype':'application/pdf'}},'patch':{}}

def test_existing_identical_file_is_not_overwritten():
    a,b=Mock(),Mock();sa,sb=storage(a),storage(b);sa.download.return_value=sb.download.return_value=b'file'
    sync._copy_file(a,b,event());sb.upload.assert_not_called();sb.remove.assert_not_called()

def test_file_conflict_is_not_overwritten():
    a,b=Mock(),Mock();sa,sb=storage(a),storage(b);sa.download.return_value=b'old';sb.download.return_value=b'new'
    with pytest.raises(ValueError,match='FILE_CONTENT_CONFLICT'):sync._copy_file(a,b,event())
    sb.upload.assert_not_called()

def test_new_file_is_checked_after_upload():
    a,b=Mock(),Mock();sa,sb=storage(a),storage(b);sa.download.return_value=b'file';sb.download.side_effect=[Missing('not found'),b'corrupted']
    with pytest.raises(ValueError,match='FILE_CHECKSUM_MISMATCH'):sync._copy_file(a,b,event())
    sb.upload.assert_called_once()

def test_delete_requires_matching_old_etag():
    a,b=Mock(),Mock();storage(a);sb=storage(b);sb.download.return_value=b'changed'
    e=event('DELETE');e['patch']={'etag':hashlib.md5(b'original').hexdigest()}
    with pytest.raises(ValueError,match='FILE_DELETE_CONFLICT'):sync._copy_file(a,b,e)
    sb.remove.assert_not_called()

@pytest.mark.parametrize('bucket',['another-project','contratos'])
def test_invalid_storage_bucket_is_rejected(bucket):
    e=event();e['row_data']['bucket_id']=bucket
    with pytest.raises(ValueError,match='INVALID_FILE'):sync._copy_file(Mock(),Mock(),e)

def test_failed_table_event_is_retried_without_losing_successful_one():
    a,b=Mock(),Mock();events=[{'id':'one','schema_name':'public'},{'id':'two','schema_name':'public'}]
    a.rpc.return_value.execute.return_value.data=events
    b.rpc.return_value.execute.return_value.data={'acked':['one'],'errors':[{'id':'two','code':'23503'}]}
    assert sync.transfer(a,b)==2
    assert a.rpc.call_args.args==('pipou_sync_ack',{'p_ids':['one'],'p_errors':[{'id':'two','code':'23503'}]})
