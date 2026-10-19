# Replay Source Failure Investigation

Juan Pablo Osorio — EGN 321 Module 7 Assignment 7.2

## 1. System Before Failure

This investigation extends my Assignment 7.1 Flask monitor using the same virtual NTC temperature history. The controlled test runs the application and supervisor, replays one record per second, and checks actual HTTP responses and SQLite data. All times below are UTC on October 18, 2026. Source timestamps remain the reconstructed classroom timestamps from Module 6; receipt timestamps describe this execution.

At 23:25:59.602, the baseline application reported HEALTHY with a current reading of 25.0 °C, data status OK and a clear temperature alert. The dashboard returned HTTP 200. SQLite contained the preserved 125-record archive and three newly processed replay rows. The worker and Flask shared PID 51760. The runtime database was readable and later passed an explicit write-transaction probe.

## 2. Failure Introduced

At 23:25:59.604, the investigation script created runtime/baseline/replay.paused. A narrow control hook stops source delivery and freezes the replay cursor while leaving the worker timer, Flask and SQLite running. This is the single selected failure scenario: stopping the replay source. It is not a damaged database or a stopped Flask process.

The expected result was an unchanged latest reading followed by STALE/DEGRADED after more than three seconds without valid input and FAILED after more than eight seconds. The actual result matched that sequence. No zero, replacement measurement or fabricated history row was inserted during the interruption. The same scenario was repeated after improving logging; it was not a different failure.

## 3. First Observable Symptom

The first observable symptom in the available evidence was the unchanged latest reading ID 3 at 23:26:01.146, when its receipt age exceeded 1.5 seconds. That is a controlled observation of a missed expected update, not proof of a physical sensor fault. The dashboard still showed HEALTHY because the three-second stale grace period had not expired.

The root cause of this controlled incident was the investigator-created pause file. The first symptom was missing new input; downstream symptoms were STALE, an unavailable current value, DEGRADED and then FAILED. Flask remained reachable. The first adverse application-log event was HEALTH_CHANGED to DEGRADED at 23:26:02.636, followed by STALE_DATA at the same millisecond. Baseline logs do not include a formal severity field. The investigator record supplies the deliberate cause; the application logs alone did not identify the actor or pause mechanism.

## 4. Log Evidence

Primary evidence is evidence/baseline/application_events.jsonl, supported by investigator.jsonl, the saved HTTP/JSON responses and diagnostic_tests.json. Event 6 changes HEALTHY to DEGRADED; event 7 records 3.089 seconds without valid data; event 9 records 8.010 seconds and the failed-data condition. Subsequent READING_PROCESSED and FAILED-to-HEALTHY events establish resumed processing.

The affected path is replay delivery and ingestion freshness. Persistent health/event writes, a recent heartbeat and successful HTTP requests show that the application was not completely stopped. The baseline logs report symptoms but omit the source-control state and source record identifier. The exported component value 'application' is an exporter label, not a detailed component field originally stored in baseline event details.

## 5. Timeline of Events

The evidence table below separates observed events from interpretation. Full UTC timestamps and source references are preserved in evidence/failure_timeline.csv. The dashboard computes health on each request, while the worker logs transitions every 0.2 seconds; therefore a dashboard observation may precede its matching log by a fraction of a second.

| Time UTC | Component | Event | Evidence | Interpretation |

|---|---|---|---|---|

| 23:25:59.602 | Dashboard | 01_normal | baseline/investigator.jsonl line 1 | Normal valid replay and available HTTP dashboard. |

| 23:25:59.604 | Replay control | FAILURE_INTRODUCED | baseline/investigator.jsonl line 2 | Investigator creates the pause file; this is the known intervention. |

| 23:26:01.146 | Ingestion | 02_first_symptom | baseline/investigator.jsonl line 3 | No new row after more than 1.5 seconds; still inside the 3-second grace period. |

| 23:26:02.556 | Health | 03_degraded | baseline/investigator.jsonl line 4 | HTTP state reports STALE and DEGRADED; current value is unavailable. |

| 23:26:02.636 | Health monitor | HEALTH_CHANGED | baseline/application_events.jsonl event 6 | First adverse application event; baseline has no explicit severity field. |

| 23:26:02.636 | Health monitor | STALE_DATA | baseline/application_events.jsonl event 7 | Dedicated stale warning after 3.089 seconds without valid data. |

| 23:26:07.558 | Health monitor | DATA_FAILED | baseline/application_events.jsonl event 9 | Source silence has exceeded the failed-data limit. |

| 23:26:07.566 | Health | 04_failed | baseline/investigator.jsonl line 5 | Valid-data age exceeds 8 seconds while HTTP remains available. |

| 23:26:07.568 | Investigator | LOG_REVIEW_AND_HYPOTHESES | baseline/investigator.jsonl line 6 | Inspect logs, pause flag, heartbeat and SQLite read/write behavior. |

| 23:26:07.568 | Replay control | RECOVERY_ACTION | baseline/investigator.jsonl line 7 | Remove the pause marker only; retain evidence and database. |

| 23:26:08.661 | Dashboard | 05_recovered | baseline/investigator.jsonl line 8 | New valid row and HEALTHY response after recovery. |

| 23:26:10.737 | Ingestion | 06_continued_input | baseline/investigator.jsonl line 9 | Two additional rows prove continued receipt. |

## 6. Possible Cause 1

Replay delivery was deliberately paused. Supporting evidence: the last reading and cursor stopped advancing while HTTP and the worker heartbeat continued; the pause file was present at the diagnostic checkpoint. Baseline application logs did not record that file or who created it.

Deterministic test: inspect the pause-file state and cursor, remove only that file, and require new reading IDs in the same process. Executed result: the file was present, the cursor stayed at 3 through the failure, and removal restored delivery without restarting Flask. This confirms the deliberately introduced mechanism for this test. In an unobserved incident, actor identity and the reason for the file's creation would still require external audit evidence.

## 7. Possible Cause 2

A persistent SQLite write failure could prevent ingestion from committing new rows. Supporting evidence initially available: the latest stored row did not change, which is compatible with either no input or blocked writes. Missing evidence at that stage: a write exception, a read-only/locking error, and a direct transactional test.

Deterministic test: run PRAGMA integrity_check and obtain a write transaction with BEGIN IMMEDIATE, insert a diagnostic event, then roll it back. Also inspect the worker heartbeat and newly persisted health events. Executed result: integrity_check returned ok; the insert and rollback succeeded; the heartbeat was recent and failure-state events persisted. This rejects a persistent database-write outage at the tested moment. It does not prove that no brief storage error ever occurred outside the observation window. The rollback left no diagnostic event falsely presented as an application event.

## 8. Recovery Procedure

At 23:26:07.568, the script removed only runtime/baseline/replay.paused. It did not delete the database, clear logs, reset the cursor or restart the application. The worker resumed from the next unconsumed source record.

The dashboard returned HEALTHY at 23:26:08.661, 1.093 seconds after the recovery action. The control-file pause lasted 7.965 seconds; the data age exceeded eight seconds because the last reading arrived shortly before the pause began. After verification, the script shut down its own supervisor and retained a consistent SQLite backup and all logs.

## 9. Verification of Recovery

Baseline recovery used the same application PID. The current value returned to 25.0 °C, data status returned to OK, the temperature alert stayed clear, and HTTP returned 200. Three replay rows before the failure remained identical, and six rows were present after continued input. All 125 Module 6 archive rows remained identical. SQLite integrity_check returned ok.

The improved rerun also passed: source input resumed, the dashboard and database remained usable, and HEALTHY returned in 0.989 seconds after removing the marker. These are two observed runs, not an availability guarantee. Sixteen automated tests passed. A separate deterministic storage test takes the system through stale recovery, activates the threshold alert with three valid 31 °C fixture samples, holds it at 29 °C, and clears it at 28 °C. Those fixture values are unit-test inputs, not measurements from the live investigation.

## 10. What the Logs Told Me

The baseline logs established normal processing, the last successful ingestion time, health transitions, the stale duration and resumed ingestion. Together with the live HTTP outputs and database probes, they distinguished a freshness failure from total Flask unavailability or persistent database failure. The saved original and improved logs allow the diagnosis to be audited. No instructor log entries were reused as execution evidence.

## 11. What the Logs Did Not Tell Me

Baseline application logs did not state that replay was paused, who paused it, the affected source record, or whether an external service or operator caused the silence. Repeated old data alone cannot distinguish a missing source from a failed ingestion/storage path. A stale warning is a symptom, not an attribution of cause.

The control-file inspection and investigator audit resolve the deliberate action in this experiment. They do not establish a physical sensor outage, network failure, power failure or actor identity in a real installation. UTC timestamps locate events; they are not proof that separate machines have synchronized clocks. The verification ran on one host.

## 12. Improvement Made

After inspecting the baseline log gap, I added SOURCE_PAUSED and SOURCE_RESUMED events when the control-file state changes. The updated event logger includes component, severity, PID, database filename, replay cursor, latest reading ID, source record ID, source timestamp and the previously persisted last-valid receipt timestamp. This context is recorded in event details. Cursor and last-valid context are read before the current tick commits; they are not claimed as post-commit state.

The improved rerun produced SOURCE_PAUSED at 23:26:58.366 with severity WARNING, component replay_source and reason 'local replay control file present'. SOURCE_RESUMED appeared at 23:27:06.390. Both identify replay.paused and the expected one-second interval. evidence/improvement_verification.json checks the new events and fields against the retained baseline. The improvement is implemented and tested, not merely recommended. It identifies this local control mechanism; it does not generalize to every possible external-source failure.

## 13. Remaining Limitations

This is a local classroom replay, not a live physical sensor deployment. The selected failure pauses input while keeping health monitoring active; it does not test a locked database, full disk, dead host, hung interpreter or interrupted power. The supervisor restarts an exited child but cannot fix a pause file that remains present. Removing that file requires an operator or the controlled investigation script.

The Flask development server is local-only. No boot service or production hosting was installed. SQLite and logs have no retention policy; an unavailable database can prevent database-backed logging. Timers use host time and the machine must remain awake. The 1.5-second diagnostic observation is a test criterion; the actual stale threshold remains three seconds. Application logs still do not authenticate the actor who creates a control file. AI assistance is disclosed in AI_LOG.md; no Ollama execution is claimed.
