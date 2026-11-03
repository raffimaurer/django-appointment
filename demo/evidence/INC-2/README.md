# INC-2 evidence

Synthetic data only. These files sit outside `appointment/`, so `manage.py test appointment` does not
discover them.

- `test-runs.txt`: baseline, pre-fix regression, and post-fix test summary lines, with the exact commands.
- `probe_related_risks.py`: bounded related-risk probes. They print observed behaviour and do not assert.
- `probe-output.txt`: actual output of the probe script on the fix commit.

The report is at [`docs/incidents/INC-2-stale-reschedule-confirmation-blocked-hour.md`](../../../docs/incidents/INC-2-stale-reschedule-confirmation-blocked-hour.md).
