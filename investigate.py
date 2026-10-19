"""Actual HTTP/SQLite investigation. Each run preserves its own evidence and DB."""
import argparse,json,os,sqlite3,subprocess,sys,time,urllib.request
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent

def run(label):
 out=ROOT/'evidence'/label
 if out.exists():raise SystemExit(f'Refusing to overwrite {out}; use a fresh project copy.')
 out.mkdir(parents=True)
 runtime=ROOT/'runtime'/label
 runtime.mkdir(parents=True,exist_ok=False)
 env=dict(os.environ,MONITOR_RUNTIME=str(runtime),MONITOR_PORT='5073',MONITOR_MODE='history',MONITOR_DIAGNOSTICS='1' if label=='improved' else '0')
 url='http://127.0.0.1:5073'
 audit=[];start=time.monotonic()
 def note(event,**detail):
  r=dict(time=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),elapsed_seconds=round(time.monotonic()-start,4),component='investigator',event=event,**detail)
  audit.append(r);(out/'investigator.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in audit));return r
 def status():
  with urllib.request.urlopen(url+'/api/status',timeout=2) as f:return json.load(f)
 def wait(pred,timeout=25):
  until=time.monotonic()+timeout
  while time.monotonic()<until:
   try:
    s=status()
    if pred(s):return s
   except OSError:pass
   time.sleep(.1)
  raise AssertionError('Expected state not observed')
 def capture(name,s):
  with urllib.request.urlopen(url,timeout=2) as f:
   html=f.read().decode();assert 'Unattended temperature monitor' in html
  (out/(name+'.json')).write_text(json.dumps(s,indent=2)+'\n')
  (out/(name+'.html')).write_text(html)
  note(name,health=s['health'],data_status=s['data_status'],current=s['current'],latest_id=s['latest']['id'],pid=s['pid'],dashboard_http=200)
 def rows():
  with sqlite3.connect(runtime/'monitor.db') as c:
   return c.execute('SELECT * FROM sensor_readings ORDER BY record_id').fetchall(),c.execute('SELECT * FROM live_readings ORDER BY id').fetchall()
 supervisor=subprocess.Popen([sys.executable,str(ROOT/'supervisor.py')],env=env)
 try:
  before=wait(lambda s:s['health']=='HEALTHY' and s['cursor']>=3)
  capture('01_normal',before);archive_before,live_before=rows()
  note('FAILURE_INTRODUCED',action='Create runtime/'+label+'/replay.paused',expected='Source stops; worker, Flask and SQLite stay running; data become stale')
  (runtime/'replay.paused').touch()
  symptom=wait(lambda s:time.time()-s['latest']['received_epoch']>1.5)
  capture('02_first_symptom',symptom)
  degraded=wait(lambda s:s['data_status']=='STALE' and s['health']=='DEGRADED');capture('03_degraded',degraded)
  failed=wait(lambda s:s['health']=='FAILED');capture('04_failed',failed)
  with sqlite3.connect(runtime/'monitor.db',timeout=2) as c:
   c.row_factory=sqlite3.Row
   state=dict(c.execute('SELECT * FROM state').fetchone())
   logs=[dict(r) for r in c.execute('SELECT * FROM events ORDER BY id')]
   integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
   c.execute('BEGIN IMMEDIATE');c.execute("INSERT INTO events(timestamp,kind,details) VALUES('probe','ROLLBACK_PROBE','{}')");c.rollback()
  probe=dict(source_pause_file_present=(runtime/'replay.paused').exists(),integrity=integrity,write_transaction_and_rollback=True,worker_heartbeat_age=time.time()-state['heartbeat'],pid_unchanged=before['pid']==failed['pid'],cursor_at_first_symptom=symptom['cursor'],cursor_at_failure=failed['cursor'])
  assert integrity=='ok' and probe['pid_unchanged'] and probe['cursor_at_first_symptom']==probe['cursor_at_failure']
  (out/'diagnostic_tests.json').write_text(json.dumps(probe,indent=2)+'\n')
  (out/'logs_reviewed_before_recovery.json').write_text(json.dumps(logs,indent=2)+'\n')
  note('LOG_REVIEW_AND_HYPOTHESES',cause1='Replay source paused',cause2='Persistent SQLite write failure blocking ingestion',tests=probe)
  note('RECOVERY_ACTION',action='Remove only replay.paused; preserve database and logs')
  (runtime/'replay.paused').unlink()
  recovered=wait(lambda s:s['health']=='HEALTHY' and s['latest']['id']>failed['latest']['id']);capture('05_recovered',recovered)
  continued=wait(lambda s:s['latest']['id']>=recovered['latest']['id']+2);capture('06_continued_input',continued)
  archive_after,live_after=rows()
  assert archive_before==archive_after and live_before==live_after[:len(live_before)]
  assert not recovered['alert'] and recovered['current'] is not None and recovered['pid']==before['pid']
  result=dict(passed=True,variant=label,archive_rows=len(archive_after),archive_unchanged=True,prior_rows_unchanged=True,rows_before=len(live_before),rows_after=len(live_after),final_health=continued['health'],same_application_pid=True,alert_clear_after_recovery=not continued['alert'],input_resumed=True,sqlite_integrity=integrity,source_pause_seconds=round(audit[-3]['elapsed_seconds']-audit[1]['elapsed_seconds'],4))
  # Exact durations are derived from named audit events, never list positions.
  times={r['event']:r['elapsed_seconds'] for r in audit}
  result['source_pause_seconds']=round(times['RECOVERY_ACTION']-times['FAILURE_INTRODUCED'],4)
  result['recovery_seconds']=round(times['05_recovered']-times['RECOVERY_ACTION'],4)
  (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');note('VERIFICATION_PASSED',**result)
 finally:
  supervisor.terminate()
  try:supervisor.wait(timeout=10)
  except subprocess.TimeoutExpired:supervisor.kill();supervisor.wait()
  if (runtime/'monitor.db').exists():
   with sqlite3.connect(runtime/'monitor.db') as c,sqlite3.connect(out/'monitor.db') as dest:
    c.backup(dest)
    records=c.execute('SELECT id,timestamp,kind,details FROM events ORDER BY id').fetchall()
   (out/'application_events.jsonl').write_text(''.join(json.dumps(dict(id=i,time=t,component='application',event=k,details=json.loads(d)))+'\n' for i,t,k,d in records))
  for f in ['supervisor.jsonl','application_console.log']:
   if (runtime/f).exists():(out/f).write_bytes((runtime/f).read_bytes())
 print(json.dumps(result,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('variant',choices=['baseline','improved']);run(p.parse_args().variant)
