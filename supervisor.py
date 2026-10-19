"""One entry point; restart a crashed child, preserve DB and log exit codes."""
import json,os,signal,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
runtime=Path(os.environ.get('MONITOR_RUNTIME',ROOT/'runtime'));runtime.mkdir(parents=True,exist_ok=True)
child=None
stopping=False
def log(kind,**fields):
    from datetime import datetime,timezone
    with (runtime/'supervisor.jsonl').open('a') as f:f.write(json.dumps(dict(timestamp=datetime.now(timezone.utc).isoformat(),kind=kind,**fields))+'\n')
def stop(*_):
    global stopping
    stopping=True
    if child and child.poll() is None:child.terminate()
for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,stop)
log('SUPERVISOR_START',pid=os.getpid())
failures=0
while not stopping:
    started=time.monotonic()
    with (runtime/'application_console.log').open('a') as output:
        child=subprocess.Popen([sys.executable,str(ROOT/'app.py')],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
        (runtime/'child.pid').write_text(str(child.pid))
        log('CHILD_STARTED',pid=child.pid)
        code=child.wait()
    log('CHILD_EXIT',pid=child.pid,exit_code=code)
    if stopping:break
    failures=failures+1 if time.monotonic()-started<10 else 0
    if failures>=5:
        log('RESTART_LIMIT_REACHED',action='Human intervention required');break
    log('RESTART_SCHEDULED',delay_seconds=1)
    time.sleep(1)
log('SUPERVISOR_STOP')
