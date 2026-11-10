"""Negative editorial reviews for paid Business assets; no erasing spend evidence."""
import sqlite3,re,time,uuid
from pathlib import Path
from business_marketing_drafts import _id as draft_id
from business_runway_video import _id as media_id

REASONS={'irrelevant_subject','near_duplicate','insufficient_motion','unreadable_typography','synthetic_artifacts','unsafe_claim','incorrect_brand'}
class ReviewError(ValueError):
 def __init__(self,message,code='invalid_review',status=422):
  super().__init__(message);self.code=code;self.status=status

def initialise(con):
 con.execute('''CREATE TABLE IF NOT EXISTS business_creative_rejections(
   id TEXT PRIMARY KEY,draft_id TEXT NOT NULL,asset_id TEXT NOT NULL,
   asset_type TEXT NOT NULL,reason TEXT NOT NULL,note TEXT NOT NULL,
   status TEXT NOT NULL DEFAULT 'rejected',created REAL NOT NULL,
   UNIQUE(draft_id,asset_id,asset_type))''')

def _row(row):
 return {'id':row['id'],'draftId':row['draft_id'],'assetId':row['asset_id'],
  'assetType':row['asset_type'],'reason':row['reason'],'note':row['note'],
  'status':row['status'],'published':False}

def reject(con,draft,asset,kind,reason,note):
 draft_id(draft);media_id(asset)
 if kind not in ('image','video'):raise ReviewError('Unsupported creative type','invalid_kind',400)
 if reason not in REASONS:raise ReviewError('Choose the specific creative fault','invalid_reason',400)
 if not isinstance(note,str) or not 12<=len(note)<=300:raise ReviewError('Give a short reason this advert cannot be used','missing_notes',400)
 table='runway_image_jobs' if kind=='image' else 'runway_video_jobs'
 row=con.execute(f'SELECT id FROM {table} WHERE id=? AND draft_id=? AND status=?',(asset,draft,'completed')).fetchone()
 if not row:raise ReviewError('Only completed assets for this exact business can be rejected','unknown_media',404)
 old=con.execute('SELECT * FROM business_creative_rejections WHERE draft_id=? AND asset_id=? AND asset_type=?',(draft,asset,kind)).fetchone()
 if old:return _row(old)
 uid=uuid.uuid4().hex
 con.execute('INSERT INTO business_creative_rejections VALUES(?,?,?,?,?,?,?,?)',
  (uid,draft,asset,kind,reason,note,'rejected',time.time()))
 con.commit()
 return _row(con.execute('SELECT * FROM business_creative_rejections WHERE id=?',(uid,)).fetchone())

def list_reviews(con,draft):
 draft_id(draft)
 return [_row(x) for x in con.execute('SELECT * FROM business_creative_rejections WHERE draft_id=? ORDER BY created',(draft,))]

def excluded(con,draft,kind):
 draft_id(draft)
 if kind not in ('image','video'):raise ReviewError('Invalid media type')
 return {row['asset_id'] for row in con.execute('SELECT asset_id FROM business_creative_rejections WHERE draft_id=? AND asset_type=? AND status=?',(draft,kind,'rejected'))}
