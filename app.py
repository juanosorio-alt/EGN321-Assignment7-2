import os, threading, time, traceback
from flask import Flask, jsonify, render_template
import monitor as m
app=Flask(__name__)
@app.get('/')
def dashboard(): return render_template('dashboard.html',d=m.snapshot())
@app.get('/api/status')
def status(): return jsonify(m.snapshot())
@app.get('/health')
def health():
    d=m.snapshot();return jsonify(health=d['health'],pid=d['pid'],restarts=d['restarts'])
def worker():
    try:
        rows=m.sequence(os.environ.get('MONITOR_MODE','history'))
        paused_before=False
        due=time.monotonic()
        while True:
            with m.connect() as c: s=dict(c.execute('SELECT * FROM state').fetchone())
            paused=(m.RUNTIME/'replay.paused').exists()
            if paused!=paused_before and m.diagnostics_enabled():
                with m.connect() as c:
                    m.event(c,'SOURCE_PAUSED' if paused else 'SOURCE_RESUMED',
                            reason='local replay control file present' if paused else 'local replay control file removed',
                            control_file='replay.paused',expected_interval_seconds=m.INTERVAL)
            paused_before=paused
            if paused:
                m.tick() # timer and database remain live; consume no source record
                due=time.monotonic()+m.INTERVAL
            elif time.monotonic()>=due:
                if s['cursor']>=len(rows):
                    m.tick(next_cycle=True)
                else: m.tick(rows[s['cursor']],advance=True)
                due=time.monotonic()+m.INTERVAL
            else: m.tick()
            time.sleep(.2)
    except Exception:
        try:
            with m.connect() as c:m.event(c,'APPLICATION_ERROR',traceback=traceback.format_exc())
        finally: os._exit(1) # allow supervisor to restart the complete application
if __name__=='__main__':
    m.initialize();m.startup()
    threading.Thread(target=worker,daemon=True).start()
    app.run(host='127.0.0.1',port=int(os.environ.get('MONITOR_PORT','5071')),debug=False,use_reloader=False)
