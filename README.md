# EGN 321 Module 7 Assignment 7.2

**Juan Pablo Osorio**

## Failure investigation and recovery

This project extends Assignment 7.1. The selected failure is **stopping the replay source while Flask, the timer and SQLite continue running**. Actual baseline and improved runs demonstrate stale data, FAILED health, diagnosis, recovery without deleting evidence, and improved source logging. Both runs preserved all 125 original Module 6 rows and all previously committed replay rows.

Read `Assignment7_2_Failure_Report_Juan_Pablo_Osorio.docx` or `Failure_Report.md` for the required 13-section investigation. `evidence/failure_timeline.csv` contains the required Time / Component / Event / Evidence / Interpretation table. Both executions ended HEALTHY; exact durations are in each run's `result.json`. Sixteen automated tests passed.

## Start the application

Use Python 3.10 or later and an awake macOS/Linux host. From this folder:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python supervisor.py
```

Visit http://127.0.0.1:5071. The single supervisor starts Flask and its replay worker, and restarts an exited child after one second. Five rapid repeated exits stop retries. Ctrl+C stops the supervisor and its child. No boot service is installed. A paused source is not an exited process, so removing the pause marker is required; process restart alone does not solve it.

The normal application defaults to enriched diagnostics. `MONITOR_DIAGNOSTICS=0` reproduces the old event detail format for the baseline investigation; it is a documented comparison switch, not the normal operating mode.

## Run verification

```bash
python -m unittest -v
python investigate.py baseline
python investigate.py improved
```

The investigation starts and stops its own supervisor on port **5073**. Do not run another application on that port. It performs normal operation, creates a pause file, observes the symptom and health transitions, reviews logs and probes SQLite, removes only the file, and verifies continued input. It exports actual HTTP HTML/JSON responses, logs, test results and a consistent database backup. Browser automation and Ollama are not required.

Each variant refuses to overwrite its evidence directory. The submitted evidence is already present. To reproduce in the same extracted folder, first **move** `evidence/baseline` and `evidence/improved` to a separate backup folder; also move any matching `runtime/baseline` or `runtime/improved` directory from an earlier local run. Keep the originals for audit. Do not delete a failed run to make its outcome disappear. The shared unit tests use temporary databases and do not change submitted evidence.

## Source and timing

`data/module6_history.db` is the unchanged primary database from [Assignment 6.1](https://github.com/juanosorio-alt/EGN321-Assignment6-1). It contains a virtual NTC sensor in °C, sampled at the student's one-second replay interval. Source dates were reconstructed in Module 6 for classroom replay; they are not acquisition timestamps. The original metadata, statuses, values and source timestamps remain in `sensor_readings`. New receipt timestamps describe replay execution and are stored separately in `live_readings`. Rejected/missing values are never replaced by zero or forward-filled. The original database hash is in `source_manifest.json`.

Normal mode repeats the stored source sequence. During a pause, the cursor does not advance and no replacement rows are inserted. The source resumes at the next unconsumed record. Archive graphs break across invalid/missing input and original run boundaries; recent history breaks across receipt gaps.

## Rules inherited from Assignment 7.1

- Accept finite 0–50 °C values subject to source status. Suspicious values remain auditable but cannot activate or clear an alert.
- Three consecutive OK samples at or above 30 °C activate a warm-condition classroom alert; an OK sample at or below 28.5 °C clears it.
- Missing, invalid and stale input reset pending persistence but do not silently clear an active temperature alert.
- More than 3 seconds since valid receipt means DEGRADED; more than 8 seconds means FAILED. RECOVERING covers initial startup before valid input; recent valid input without an active alert means HEALTHY.
- The dashboard displays Unavailable for stale current values. Its HTTP health calculation can precede a timer log by a fraction of a second.
- Health timing continues every 0.2 seconds even when input stops. Source timestamps do not control freshness.

## Failure and recovery controls

For the ordinary runtime, create the empty file `runtime/replay.paused` to stop replay and remove only that file to resume it. The automated investigator uses separate per-run runtime folders. These are explicit local test controls, not evidence of a physical sensor being unplugged. Their presence does not stop Flask, freeze the worker timer or close SQLite.

Baseline diagnosis distinguishes two hypotheses: paused source delivery and persistent database write failure. The investigator checks the pause marker and frozen cursor, then runs SQLite integrity_check and a write transaction with rollback. Successful database writes reject a persistent storage outage at that observation, not every possible historical transient. Removing the marker restores data without restarting or erasing history.

## Implemented improvement

The default application logs `SOURCE_PAUSED` and `SOURCE_RESUMED` with a reason and control-file name. Event details now include component, severity, PID, database filename, cursor before the tick commits, latest reading/source IDs, original source timestamp and the previously persisted last-valid receipt timestamp. The latter is pre-commit context and may refer to the prior reading during a processing event.

`evidence/improvement_verification.json` compares actual baseline and improved logs. The baseline has no explicit source-pause event; the rerun has both source transitions and the new fields. The tests also check enriched record context and activation/hysteresis/clearing after a stale episode in an isolated fixture database.

## Logs and evidence map

Each `evidence/baseline/` and `evidence/improved/` directory contains:

| File | Evidence |
|---|---|
| `01_normal.json` and `.html` | Normal status, latest reading, dashboard and alert state |
| `02_first_symptom.json` and `.html` | Old latest record before the stale grace period expires |
| `03_degraded.json` and `.html` | STALE, no current value, DEGRADED health |
| `04_failed.json` and `.html` | Failed data freshness with working HTTP dashboard |
| `diagnostic_tests.json` | Pause flag, cursor, heartbeat, database integrity and successful write/rollback |
| `logs_reviewed_before_recovery.json` | Event evidence inspected before the recovery action |
| `05_recovered.json` and `.html` | Valid new input, clear alert and HEALTHY state |
| `06_continued_input.json` and `.html` | Additional new records after initial recovery |
| `application_events.jsonl` | Ordered application event export, including original SQLite event IDs |
| `investigator.jsonl` | Exact action/observation times, hypotheses, probes and verification |
| `supervisor.jsonl` and `application_console.log` | Process and HTTP logs |
| `monitor.db` | Consistent post-test database backup with retained evidence |
| `result.json` | Recovery and preservation assertions |

Numbered HTML files are real HTTP responses saved during execution, **not screenshots or a live dashboard**. Their embedded state represents the capture time. The assignment accepts screenshots or output; this package supplies both machine-readable JSON and rendered HTML output. Request pairs can differ by milliseconds. In baseline exports, the outer `component: application` is an export label; detailed component metadata was added only in improved event details.

Runtime logs are stored in SQLite's `events` table, `runtime/supervisor.jsonl`, and `runtime/application_console.log`. Each test uses its own runtime folder. Neither the instructor's logs nor his reported outcomes are reused here.

## Limitations and intervention

These tests establish local replay-source pause/recovery, not physical sensor or network reliability. They do not demonstrate recovery from power loss, failed storage, a hung interpreter, host suspension or loss of the supervisor. Corruption, permissions, full disks, persistent pause controls and crash loops require human intervention. A source-control event cannot authenticate who changed the file. Database-backed logs may fail when the database itself fails. Flask is local-only and uses its development server; logs and databases have no automatic retention policy. UTC wall-clock timing assumes a stable host clock. No background service remains installed after verification.

## References and AI disclosure

- Base system: https://github.com/juanosorio-alt/EGN321-Assignment7-1
- Instructor workflow: https://github.com/ivansuarez-AU/EGN321_Module7_Assignment7_2
- AI contributions and actual verification are recorded in `AI_LOG.md`. Codex was used; Ollama was not run.

GitHub repository: https://github.com/juanosorio-alt/EGN321-Assignment7-2
