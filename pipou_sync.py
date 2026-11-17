"""Bounded, durable compatibility bridge for reviewed RH tables only.
No payload, credential, employee identifier or binary content is logged.
"""
import asyncio
import hashlib
import logging
import os
from urllib.parse import quote
import supabase_client as db
log=logging.getLogger('pipou.sync')
BUCKETS={'employee-documents','documents','punch-photos','payroll-reports','employee-docs','candidate-cvs','recruitment-interviews','ponto-fotos','contratos'}

def _copy_file(source,target,event):
    row=event.get('row_data') or event['record_key'];bucket=row.get('bucket_id');name=row.get('name')
    if bucket not in BUCKETS or not isinstance(name,str) or any(x in ('.','..') for x in name.split('/')):raise ValueError('INVALID_FILE')
    from_storage=source.storage.from_(bucket);to_storage=target.storage.from_(bucket)
    if event['operation']=='DELETE':
        # Never remove a different/newer binary that happens to reuse its path.
        try:existing=to_storage.download(name)
        except Exception as error:
            status=getattr(error,'status',getattr(error,'status_code',None))
            if str(status) in ('404','400') and 'not found' in str(error).lower():return
            raise
        etag=(event.get('patch') or {}).get('etag')
        if not etag or etag.strip('"')!=hashlib.md5(existing).hexdigest():raise ValueError('FILE_DELETE_CONFLICT')
        to_storage.remove([name]);return
    payload=from_storage.download(name)
    try:
        existing=to_storage.download(name)
    except Exception as error:
        status=getattr(error,'status',getattr(error,'status_code',None))
        if str(status) not in ('400','404') or 'not found' not in str(error).lower():raise
        existing=None
    if existing is not None:
        if hashlib.sha256(existing).digest()!=hashlib.sha256(payload).digest():raise ValueError('FILE_CONTENT_CONFLICT')
        return
    mime=(row.get('metadata') or {}).get('mimetype') or 'application/octet-stream'
    try:to_storage.upload(name,payload,{'content-type':mime,'upsert':'false'})
    except Exception:
        if hashlib.sha256(to_storage.download(name)).digest()!=hashlib.sha256(payload).digest():raise
    if hashlib.sha256(to_storage.download(name)).digest()!=hashlib.sha256(payload).digest():raise ValueError('FILE_CHECKSUM_MISMATCH')
    owner=row.get('owner_id') or row.get('owner')
    if owner:target.rpc('pipou_sync_storage_owner',{'p_bucket':bucket,'p_name':name,'p_owner':owner}).execute()

def transfer(source,target):
    events=source.rpc('pipou_sync_claim',{'p_limit':25}).execute().data or []
    if not events:return 0
    rows=[x for x in events if x['schema_name']!='storage'];acked=[];errors=[]
    if rows:
        # Bound request size even when an import contains a large JSON payload.
        import json
        batch=[];size=0
        for row in rows+[None]:
            width=len(json.dumps(row)) if row is not None else 0
            if batch and (row is None or size+width>4000000):
                result=target.rpc('pipou_sync_apply',{'p_events':batch}).execute().data
                acked.extend(result.get('acked',[]));errors.extend(result.get('errors',[]));batch=[];size=0
            if row is not None:batch.append(row);size+=width
    for event in events:
        if event['schema_name']!='storage':continue
        try:_copy_file(source,target,event);acked.append(event['id'])
        except Exception as error:
            code=str(error) if isinstance(error,ValueError) else type(error).__name__
            errors.append({'id':event['id'],'code':code[:80]})
    source.rpc('pipou_sync_ack',{'p_ids':acked,'p_errors':errors}).execute()
    if errors:log.warning('Compatibility bridge: %s events waiting for retry or conflict review',len(errors))
    return len(events)

async def run():
    while True:
        try:
            if os.environ.get('PIPOU_SYNC_ENABLED')=='true':
                old=db.get_client();new=db.get_people_client()
                if old is new:raise RuntimeError('Dedicated database is required')
                await asyncio.to_thread(transfer,old,new)
                await asyncio.to_thread(transfer,new,old)
        except asyncio.CancelledError:raise
        except Exception as error:log.warning('Compatibility bridge unavailable: %s',type(error).__name__)
        await asyncio.sleep(5)
