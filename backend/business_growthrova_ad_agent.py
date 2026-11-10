"""Growthrova's resumable ad agent. Existing writer/image services own spending.
This is not Runway Ads. Agent recommendations are not owner approval/favourites.
"""
from contextlib import closing
import hashlib,json,time,uuid
from flask import jsonify,request
from business_marketing_drafts import MarketingDraftError,_id
from business_growthrova_writer import source_material
from business_brand_render import validate_brand,BrandRenderError
from business_growthrova_runway_images import MODEL
from business_nano_banana_pro import MODEL as GOOGLE_MODEL
import business_growthrova_creative_memory as creative_memory

def _hash(value):
 return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def _child(run,label):
 return hashlib.sha256((run+':'+label).encode()).hexdigest()[:32]
def public(run):
 return {**{k:v for k,v in run.items() if k not in ('sourceHash','leaseToken','leaseUntil')},
         'working':run.get('leaseUntil',0)>time.time()}
def register_ad_agent(app,repo,root,writer_config,image_config,writer,images):
 with closing(repo._connect()) as con:
  con.execute('''CREATE TABLE IF NOT EXISTS growthrova_ad_agent_runs(
   document_id TEXT NOT NULL,run_id TEXT NOT NULL,fingerprint TEXT NOT NULL,
   result_json TEXT NOT NULL,PRIMARY KEY(document_id,run_id),UNIQUE(document_id,fingerprint))''')
  con.commit()
 def image_ceiling():
  return image_config.output_cost_microusd if image_config.model==MODEL else image_config.call_cap_microusd
 def load(ident,run_id):
  _id(run_id)
  with closing(repo._connect()) as con:
   row=con.execute('SELECT result_json FROM growthrova_ad_agent_runs WHERE document_id=? AND run_id=?',(ident,run_id)).fetchone()
  if not row:raise MarketingDraftError('Ad agent run not found.','ad_agent_missing',404)
  return json.loads(row[0])
 def unpack(value):
  response=app.make_response(value)
  body=response.get_json()
  if response.status_code>=400:
   raise MarketingDraftError((body or {}).get('error','Ad agent step could not complete.'),(body or {}).get('code','ad_agent_step_held'),response.status_code)
  if not isinstance(body,dict):raise MarketingDraftError('Invalid saved agent step.','ad_agent_step_held',409)
  return body

 def bind_plan(organisation_id,ident,saved,run,result):
  run['planOperationId']=result['operationId']
  if result['state']=='pending':
   run.update(state='planning',stage='Planning advert concepts')
   return
  if result['state']!='proposed':run.update(state='held',stage='Concepts need review',issues=result.get('issues',[]))
  else:
   recommendations=result.get('recommendations',[])
   ids=[r['conceptId'] for r in recommendations]
   if len(set(ids))<run['count']:raise MarketingDraftError('The planner did not recommend enough distinct concepts. Review its saved plan.')
   run['concepts']=[next(c for c in result['concepts'] if c['id']==cid) for cid in ids[:run['count']]]
   run['selectionBy']='agent_editorial_recommendation'
   batch=unpack(images['prepare'](organisation_id,ident,saved,dict(batchId=_child(run['runId'],'batch'),planOperationId=result['operationId'],
     expectedRevision=run['expectedRevision'],day=run['day'],size=run['size'],quality='standard',renderingMode='complete_advert',
     conceptIds=[c['id'] for c in run['concepts']])))
   run.update(batchId=batch['batchId'],state='ready',stage='Generate advert drafts')
 @app.get(root+'/<ident>/ad-agent')
 def agent_status(organisation_id,ident):
  saved=repo.read(organisation_id,ident)
  with closing(repo._connect()) as con:
   rows=con.execute('SELECT result_json FROM growthrova_ad_agent_runs WHERE document_id=? ORDER BY rowid DESC LIMIT 10',(ident,)).fetchall()
  return jsonify(available=bool(writer_config.available() and image_config.available() and image_config.model in (MODEL, GOOGLE_MODEL)),
    imageReservationMicrousd=image_ceiling(),
    providerLabel='Google Gemini · Nano Banana Pro' if image_config.model==GOOGLE_MODEL else 'Runway · Nano Banana Pro', planningCapMicrousd=writer_config.call_cap_microusd,
    revision=saved['revision'],runs=[public(json.loads(r[0])) for r in rows],
    message='Create complete advert drafts from your saved brief. Agent choices remain drafts for your review.')
 @app.post(root+'/<ident>/ad-agent')
 def start_agent(organisation_id,ident):
  saved=repo.read(organisation_id,ident);data=request.get_json(silent=True)
  fields={'runId','expectedRevision','day','count','size','tone'}
  if not isinstance(data,dict) or set(data)!=fields:raise MarketingDraftError('Choose the saved post, canvas and one to three advert drafts.')
  _id(data['runId'])
  if type(data['expectedRevision']) is not int or data['expectedRevision']!=saved['revision']:raise MarketingDraftError('Campaign changed. Save and reopen before running the ad agent.','revision_conflict',409)
  if type(data['count']) is not int or data['count'] not in (1,2,3):raise MarketingDraftError('Choose one to three advert drafts.')
  if type(data['day']) is not int or not any(p['day']==data['day'] for p in saved['document']['posts']):raise MarketingDraftError('Choose a saved post.')
  if data['size'] not in ('square_2k','portrait_2k','landscape_2k') or data['tone'] not in ('warm and informative','calm and professional','direct and practical'):raise MarketingDraftError('Choose a supported canvas and tone.')
  source_material(saved['document'])
  try:validate_brand(saved['document'].get('brandKit'))
  except BrandRenderError:raise MarketingDraftError('Save the business brand before starting the ad agent.') from None
  with closing(repo._connect()) as con:
   con.execute('BEGIN IMMEDIATE')
   memory=creative_memory.context(con,repo._scope(organisation_id),ident)
   fingerprint=_hash([saved['document'],{k:v for k,v in data.items() if k!='runId'},image_config.model,memory['fingerprint'],creative_memory.PIPELINE_VERSION])
   row=con.execute('SELECT fingerprint,result_json FROM growthrova_ad_agent_runs WHERE document_id=? AND run_id=?',(ident,data['runId'])).fetchone()
   if row:
    if row['fingerprint']!=fingerprint:raise MarketingDraftError('This agent run has different inputs.','operation_conflict',409)
    return jsonify(public(json.loads(row['result_json'])))
   row=con.execute('SELECT result_json FROM growthrova_ad_agent_runs WHERE document_id=? AND fingerprint=?',(ident,fingerprint)).fetchone()
   if row:return jsonify(public(json.loads(row[0])))
   if not writer_config.available() or not image_config.available() or image_config.model not in (MODEL, GOOGLE_MODEL):raise MarketingDraftError('The ad agent needs the configured campaign writer and a supported image provider.','ad_agent_unavailable',503)
   if images['source_choice'](con,ident)['route'] not in ('create','mix'):raise MarketingDraftError('Choose Create new images or Mix both before starting the ad agent.','image_source_choice',409)
   used=con.execute('SELECT COALESCE(SUM(reservation),0) FROM growthrova_image_requests').fetchone()[0]
   if used+data['count']*image_ceiling()>image_config.budget_microusd:raise MarketingDraftError('Image budget cannot cover this agent run. No generation was requested.','image_budget_held',409)
   run={**data,'sourceHash':_hash(saved['document']),'state':'planned','stage':'Plan concepts','concepts':[],'artifacts':[],
        'completedCount':0,'issues':[],'approved':False,'canPublish':False,'canSpend':False,
        'imageModel':image_config.model,'writerModel':writer_config.model,'creativeMemoryFingerprint':memory['fingerprint'],'agent':'Growthrova ad agent',
        'maximumImageReservationMicrousd':data['count']*image_ceiling(),
        'maximumPlanningReservationMicrousd':writer_config.call_cap_microusd,'leaseUntil':0}
   con.execute('INSERT INTO growthrova_ad_agent_runs VALUES(?,?,?,?)',(ident,data['runId'],fingerprint,json.dumps(run)));con.commit()
  return jsonify(public(run))
 @app.post(root+'/<ident>/ad-agent/<run_id>/advance')
 def advance_agent(organisation_id,ident,run_id):
  saved=repo.read(organisation_id,ident)
  if request.get_json(silent=True)!={}:raise MarketingDraftError('Advance the same saved agent run without changing its inputs.')
  run=load(ident,run_id)
  if run['sourceHash']!=_hash(saved['document']) or run['expectedRevision']!=saved['revision']:raise MarketingDraftError('Campaign changed. Existing agent work is retained; start a run for the saved revision.','revision_conflict',409)
  if run['state'] in ('completed','held'):return jsonify(public(run))
  if run['imageModel']!=image_config.model or run['writerModel']!=writer_config.model:
   raise MarketingDraftError('Agent model settings changed. Existing work is retained; no provider was called.','ad_agent_settings_changed',409)

  token=uuid.uuid4().hex
  with closing(repo._connect()) as con:
   con.execute('BEGIN IMMEDIATE')
   row=con.execute('SELECT result_json FROM growthrova_ad_agent_runs WHERE document_id=? AND run_id=?',(ident,run_id)).fetchone()
   run=json.loads(row[0])
   memory=creative_memory.context(con,repo._scope(organisation_id),ident)
   if run.get('creativeMemoryFingerprint') != memory['fingerprint']:
    raise MarketingDraftError('Brand references or creative results changed. Existing work is retained; start a new run.','creative_memory_changed',409)
   if run.get('leaseUntil',0)>time.time():return jsonify(public(run))
   run.update(leaseToken=token,leaseUntil=time.time()+135)
   con.execute('UPDATE growthrova_ad_agent_runs SET result_json=? WHERE document_id=? AND run_id=?',(json.dumps(run),ident,run_id));con.commit()
  try:
   if not run.get('planOperationId'):
    result=unpack(writer['execute'](organisation_id,ident,saved,dict(operationId=_child(run_id,'plan'),expectedRevision=run['expectedRevision'],
       tone=run['tone'],repairOf='',creativePlan={'mode':'initial','parentOperationId':'','conceptId':'','conceptCount':6}),background=True))
    bind_plan(organisation_id,ident,saved,run,result)
   elif not run.get('batchId'):
    result=unpack(writer['refresh'](organisation_id,ident,run['planOperationId']))
    bind_plan(organisation_id,ident,saved,run,result)
   else:
    with closing(repo._connect()) as con:
     row=con.execute('SELECT batch_json FROM growthrova_image_batches WHERE document_id=? AND batch_id=?',(ident,run['batchId'])).fetchone()
     if not row:raise MarketingDraftError('Saved agent image set is missing.')
     batch=json.loads(row[0]);slot=None;candidate=None;artifacts=[]
     for item in batch['slots']:
      row=con.execute('SELECT result_json FROM growthrova_image_requests WHERE document_id=? AND operation_id=?',(ident,item['operationId'])).fetchone()
      candidate=json.loads(row[0]) if row else None
      if candidate:
       candidate=images['observe'](con,ident,saved,candidate)
      if candidate and candidate['state'] in ('proposed','held'):
       artifacts.append(candidate)
       if candidate['state']=='held' and candidate.get('technicalReview',{}).get('flags'):
        run.update(state='held',stage='Advert needs technical attention',issues=candidate.get('issues',[]));break
       continue
      slot=item;break
    if run['state']!='held':
     if slot is None:
      needs_review=any(item['state']=='held' for item in artifacts)
      run.update(state='review' if needs_review else 'completed',stage='Advert needs review' if needs_review else 'Ready for your review')
     else:
      if candidate:
       if candidate.get('providerTaskId'):
        result=unpack(images['refresh'](organisation_id,ident,slot['operationId']))
       else:result=candidate
      else:result=unpack(images['execute'](organisation_id,ident,saved,slot['inputs'],batch=batch))
      if result['state'] in ('proposed','held'):artifacts.append(result)
      if result['state'] in ('held','uncertain'):
       technical=bool(result.get('technicalReview',{}).get('flags'))
       blocked=result['state']=='uncertain' or technical
       all_generated=len(artifacts)==run['count']
       run.update(state='held' if blocked else ('review' if all_generated else 'ready'),
                  stage='Advert needs technical attention' if blocked else ('Advert needs review' if all_generated else 'Generate next advert'),
                  issues=result.get('issues',[]))
      elif result['state']=='pending':run.update(state='generating',stage='Generating advert '+str(slot['index']+1)+' of '+str(run['count']))
      else:run.update(state='completed' if len(artifacts)==run['count'] else 'ready',stage='Ready for your review' if len(artifacts)==run['count'] else 'Generate next advert')
    run.update(artifacts=artifacts,completedCount=len(artifacts))
  except MarketingDraftError as exc:
   run.update(state='held',stage='Agent needs attention',issues=[str(exc)])
  except (ValueError,TypeError,KeyError):
   # Durable child operations remain in existing ledgers; never make an
   # automatic new operation to repair unknown provider/contract outcomes.
   run.update(state='held',stage='Agent needs attention',issues=['A saved agent step could not complete. Inspect its existing requests before continuing.'])
  finally:
   run.pop('leaseToken',None);run['leaseUntil']=0
   with closing(repo._connect()) as con:
    row=con.execute('SELECT result_json FROM growthrova_ad_agent_runs WHERE document_id=? AND run_id=?',(ident,run_id)).fetchone()
    if json.loads(row[0]).get('leaseToken')==token:
     con.execute('UPDATE growthrova_ad_agent_runs SET result_json=? WHERE document_id=? AND run_id=?',(json.dumps(run),ident,run_id));con.commit()
  repo.read(organisation_id,ident)
  return jsonify(public(run))
