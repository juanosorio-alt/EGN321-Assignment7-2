import unittest
import monitor as m
class LogicTests(unittest.TestCase):
 def test_persistence(self):
  active,count=False,0
  for i in range(3):
   active,count=m.alert_step(active,count,31,True)
   self.assertEqual(active,i==2)
 def test_noise_resets_count(self):
  self.assertEqual(m.alert_step(False,2,29,True),(False,0))
 def test_invalid_resets_count(self):
  self.assertEqual(m.alert_step(False,2,None,False),(False,0))
 def test_hysteresis(self):
  self.assertTrue(m.alert_step(True,3,29,True)[0]);self.assertFalse(m.alert_step(True,3,28.5,True)[0])
 def test_missing_does_not_clear(self):self.assertTrue(m.alert_step(True,3,None,False)[0])
 def test_validation(self):
  for v in [None,'','bad','nan','inf',80]:self.assertIsNone(m.validation(v,'OK')[0])
  self.assertEqual(m.validation(25,'OK'),(25,'OK'))
 def test_source_rejection_preserved(self):self.assertEqual(m.validation(25,'OUT_OF_RANGE'),(None,'OUT_OF_RANGE'))
 def test_health_timeout_without_arrivals(self):
  self.assertEqual(m.health_state(2,1,0,'OK',False),'HEALTHY')
  self.assertEqual(m.health_state(5,1,0,'OK',False),'DEGRADED')
  self.assertEqual(m.health_state(10,1,0,'OK',False),'FAILED')
 def test_recovering_and_alert(self):
  self.assertEqual(m.health_state(1,None,0,'MISSING',False),'RECOVERING')
  self.assertEqual(m.health_state(2,1,0,'OK',True),'DEGRADED')

class DatabaseTests(unittest.TestCase):
 def setUp(self):
  import tempfile
  from pathlib import Path
  self.temp=tempfile.TemporaryDirectory();self.old=(m.RUNTIME,m.DB)
  m.RUNTIME=Path(self.temp.name);m.DB=m.RUNTIME/'monitor.db';m.initialize();m.startup()
 def tearDown(self):
  m.RUNTIME,m.DB=self.old;self.temp.cleanup()
 def test_archive_preserved(self):
  import sqlite3
  with sqlite3.connect(m.ROOT/'data/module6_history.db') as original,m.connect() as c:
   self.assertEqual(original.execute('SELECT * FROM sensor_readings').fetchall(),[tuple(x) for x in c.execute('SELECT * FROM sensor_readings')])
 def test_database_null_and_checkpoint(self):
  m.tick(dict(raw_value=None,status='MISSING',provenance='unit_test'),advance=True)
  with m.connect() as c:
   self.assertIsNone(c.execute('SELECT accepted_value FROM live_readings').fetchone()[0])
   self.assertEqual(c.execute('SELECT cursor FROM state').fetchone()[0],1)
 def test_alert_state_survives_restart(self):
  for _ in range(3):m.tick(dict(raw_value=31,status='OK',provenance='unit_test'),advance=True)
  m.startup()
  with m.connect() as c:
   s=c.execute('SELECT * FROM state').fetchone()
   self.assertEqual(s['alert'],1);self.assertEqual(s['cursor'],3);self.assertEqual(s['high_count'],0)
 def test_stale_resets_pending_count(self):
  for t in [100,101]:m.tick(dict(raw_value=31,status='OK',provenance='unit_test'),now=t)
  m.tick(now=106)
  m.tick(dict(raw_value=31,status='OK',provenance='unit_test'),now=107)
  with m.connect() as c:self.assertEqual(c.execute('SELECT alert FROM state').fetchone()[0],0)

 def test_stale_event_even_when_invalid_arrivals_continue(self):
  m.tick(dict(raw_value=25,status='OK',provenance='unit_test'),now=100)
  m.tick(dict(raw_value=None,status='MISSING',provenance='unit_test'),now=104)
  with m.connect() as c:
   self.assertEqual(c.execute("SELECT count(*) FROM events WHERE kind='STALE_DATA'").fetchone()[0],1)

 def test_enriched_context(self):
  import json
  m.tick(dict(raw_value=25,status='OK',provenance='unit_test',record_id=1,timestamp='2026-10-01T12:00:00'))
  with m.connect() as c:
   d=json.loads(c.execute("SELECT details FROM events WHERE kind='READING_PROCESSED' ORDER BY id DESC LIMIT 1").fetchone()[0])
   self.assertEqual(d['component'],'ingestion');self.assertEqual(d['source_record_id'],1)
   self.assertEqual(d['latest_reading_id'],1);self.assertEqual(d['severity'],'INFO')
 def test_alerts_after_stale_recovery(self):
  import json
  row=lambda v:dict(raw_value=v,status='OK',provenance='unit_test')
  m.tick(row(25),now=100);m.tick(now=110);m.tick(row(25),now=111)
  for t in [112,113,114]:m.tick(row(31),now=t)
  with m.connect() as c:self.assertEqual(c.execute('SELECT alert FROM state').fetchone()[0],1)
  m.tick(row(29),now=115)
  with m.connect() as c:self.assertEqual(c.execute('SELECT alert FROM state').fetchone()[0],1)
  m.tick(row(28),now=116)
  with m.connect() as c:
   self.assertEqual(c.execute('SELECT alert FROM state').fetchone()[0],0)
   kinds=[r[0] for r in c.execute('SELECT kind FROM events')]
   self.assertIn('ALERT_ACTIVATED',kinds);self.assertIn('ALERT_CLEARED',kinds)

if __name__=='__main__':unittest.main()
