"""Transactional replay monitor; historical timestamps are never overwritten."""
import json, math, os, sqlite3, time
from pathlib import Path
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parent
RUNTIME = Path(os.environ.get('MONITOR_RUNTIME', ROOT / 'runtime'))
DB = RUNTIME / 'monitor.db'
INTERVAL = 1.0
STALE = 3.0
FAILED = 8.0
TRIGGER, CLEAR, PERSISTENCE = 30.0, 28.5, 3

def utc(t=None):
    return datetime.fromtimestamp(time.time() if t is None else t, timezone.utc).isoformat(timespec='milliseconds')

def connect():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c

def diagnostics_enabled():
    return os.environ.get('MONITOR_DIAGNOSTICS','1')!='0'

def event(c, kind, **details):
    if diagnostics_enabled():
        component = ('replay_source' if kind.startswith('SOURCE_') else
                     'health_monitor' if kind in ('HEALTH_CHANGED','STALE_DATA','DATA_FAILED') else
                     'alert_engine' if kind.startswith('ALERT_') else 'ingestion')
        severity = 'ERROR' if kind in ('DATA_FAILED','APPLICATION_ERROR') else 'WARNING' if kind in ('SOURCE_PAUSED','STALE_DATA','MISSING_OR_REJECTED') else 'INFO'
        state=c.execute('SELECT cursor,last_valid,last_received FROM state').fetchone()
        last=c.execute('SELECT id,source_record_id,source_timestamp FROM live_readings ORDER BY id DESC LIMIT 1').fetchone()
        context=dict(component=component,severity=severity,pid=os.getpid(),
                     database='monitor.db',cursor_before_tick=state['cursor'],
                     last_valid_received_at=utc(state['last_valid']) if state['last_valid'] is not None else None,
                     latest_reading_id=last['id'] if last else None,
                     source_record_id=last['source_record_id'] if last else None,
                     source_timestamp=last['source_timestamp'] if last else None)
        details={**context,**details}
    c.execute('INSERT INTO events(timestamp,kind,details) VALUES(?,?,?)', (utc(), kind, json.dumps(details)))

def initialize():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if not DB.exists():
        with sqlite3.connect(ROOT/'data/module6_history.db') as src, sqlite3.connect(DB) as dest:
            src.backup(dest)
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS live_readings(id INTEGER PRIMARY KEY, received_at TEXT, received_epoch REAL,
          source_timestamp TEXT, source_record_id INTEGER, raw_value TEXT, accepted_value REAL, status TEXT,
          provenance TEXT, cycle INTEGER);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,timestamp TEXT,kind TEXT,details TEXT);
        CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),cursor INTEGER,cycle INTEGER,
          high_count INTEGER,alert INTEGER,last_valid REAL,last_received REAL,health TEXT,started REAL,
          heartbeat REAL,pid INTEGER,restarts INTEGER);
        INSERT OR IGNORE INTO state VALUES(1,0,0,0,0,NULL,NULL,'RECOVERING',0,0,0,0);
        ''')

def startup():
    with connect() as c:
        s=dict(c.execute('SELECT * FROM state').fetchone())
        restarted=s['pid'] != 0
        c.execute("UPDATE state SET high_count=0,health='RECOVERING',started=?,heartbeat=?,pid=?,restarts=restarts+?", (time.time(),time.time(),os.getpid(),int(restarted)))
        event(c,'APPLICATION_RESTART' if restarted else 'APPLICATION_START',pid=os.getpid(),cursor=s['cursor'])

def alert_step(active, count, value, valid):
    if not valid: return active,0
    if active: return (False,0) if value <= CLEAR else (True,count)
    count = count+1 if value>=TRIGGER else 0
    return count>=PERSISTENCE,count

def validation(raw, source_status):
    if source_status=='MISSING' or raw is None or str(raw).strip()=='': return None,'MISSING'
    try: value=float(raw)
    except (TypeError,ValueError): return None,'INVALID'
    if not math.isfinite(value): return None,'INVALID'
    if source_status not in ('OK','SUSPICIOUS'): return None,source_status
    if not 0<=value<=50: return None,'OUT_OF_RANGE'
    # Suspicious records stay auditable but are not used to activate or clear alerts.
    if source_status=='SUSPICIOUS': return value,'SUSPICIOUS'
    return value,'OK'

def health_state(now,last_valid,started,status,alert):
    age=now-(last_valid if last_valid is not None else started)
    if age>FAILED: return 'FAILED'
    if age>STALE: return 'DEGRADED'
    if last_valid is None: return 'RECOVERING'
    if status!='OK' or alert: return 'DEGRADED'
    return 'HEALTHY'

def tick(row=None, advance=False, now=None, next_cycle=False):
    now=time.time() if now is None else now
    with connect() as c:
        s=dict(c.execute('SELECT * FROM state').fetchone())
        last=c.execute('SELECT status FROM live_readings ORDER BY id DESC LIMIT 1').fetchone()
        status=last['status'] if last else 'MISSING'
        active,count=bool(s['alert']),s['high_count']
        lv,lr=s['last_valid'],s['last_received']
        if lv is not None and now-lv>STALE: count=0
        if row is not None:
            value,status=validation(row.get('raw_value'),row['status'])
            lr=now
            valid=status=='OK' and value is not None
            if valid: lv=now
            active,count=alert_step(active,count,value,valid)
            c.execute('INSERT INTO live_readings(received_at,received_epoch,source_timestamp,source_record_id,raw_value,accepted_value,status,provenance,cycle) VALUES(?,?,?,?,?,?,?,?,?)',
                (utc(now),now,row.get('timestamp'),row.get('record_id'),str(row.get('raw_value')) if row.get('raw_value') is not None else None,value,status,row['provenance'],s['cycle']))
            event(c,'READING_PROCESSED',status=status,value=value,provenance=row['provenance'])
            if status!='OK': event(c,'MISSING_OR_REJECTED',status=status)
        health=health_state(now,lv,s['started'],status,active)
        if active!=bool(s['alert']): event(c,'ALERT_ACTIVATED' if active else 'ALERT_CLEARED',value=row.get('raw_value') if row else None)
        if health!=s['health']: event(c,'HEALTH_CHANGED',previous=s['health'],current=health)
        old_age=now-(s['last_valid'] if s['last_valid'] is not None else s['started'])
        if now-(lv if lv is not None else s['started'])>STALE and s['heartbeat']-(s['last_valid'] if s['last_valid'] is not None else s['started'])<=STALE:
            event(c,'STALE_DATA',seconds_without_valid=old_age)
        if row is None and old_age>FAILED and s['health']!='FAILED': event(c,'DATA_FAILED',seconds_without_valid=old_age)
        c.execute('UPDATE state SET cursor=?,cycle=?,high_count=?,alert=?,last_valid=?,last_received=?,health=?,heartbeat=?',
            (0 if next_cycle else s['cursor']+int(advance),s['cycle']+int(next_cycle),count,int(active),lv,lr,health,now))

def sequence(mode):
    if mode=='demo':
        # Explicit injected fixtures, not claimed as measured sensor evidence.
        values=[25]*5+[31]*6+[28]*5+[None]*2+['bad']+[None]*10+[25]*8
        result=[]
        for i,v in enumerate(values):
            if 19<=i<29: result.append(None) # no arrivals: timer must still advance
            else: result.append(dict(raw_value=v,status='MISSING' if v is None else 'OK',provenance='injected_recovery_test_fixture'))
        return result
    with connect() as c:
        return [dict(r,provenance='module6_classroom_replay') for r in c.execute('SELECT record_id,timestamp,raw_value,status FROM sensor_readings ORDER BY record_id')]

def snapshot():
    now=time.time()
    with connect() as c:
        s=dict(c.execute('SELECT * FROM state').fetchone())
        rows=[dict(r) for r in c.execute('SELECT * FROM live_readings ORDER BY id DESC LIMIT 80')][::-1]
        archive=[dict(r) for r in c.execute('SELECT record_id,run_id,sample_number,timestamp,accepted_value,status FROM sensor_readings ORDER BY record_id')]
        events=[dict(r) for r in c.execute('SELECT * FROM events ORDER BY id DESC LIMIT 12')]
    latest=rows[-1] if rows else None
    status=latest['status'] if latest else 'MISSING'
    h=health_state(now,s['last_valid'],s['started'],status,s['alert'])
    if now-s['heartbeat']>FAILED: h='FAILED'
    fresh=bool(latest and status=='OK' and now-latest['received_epoch']<=STALE)
    return dict(health=h,alert=bool(s['alert']),data_status=('STALE' if latest and now-latest['received_epoch']>STALE else status),
                current=latest['accepted_value'] if fresh else None,latest=latest,rows=rows,archive=archive,events=events,
                pid=s['pid'],restarts=s['restarts'],cursor=s['cursor'],server_time=utc(),mode=os.environ.get('MONITOR_MODE','history'))
