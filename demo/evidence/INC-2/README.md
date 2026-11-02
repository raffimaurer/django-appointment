# INC-2 related-risk evidence (synthetic)

Bounded (10-minute) related-risk probes for
[issue #2](https://github.com/raffimaurer/django-appointment/issues/2). These files sit outside
`appointment/` and do not match `test*.py`, so `manage.py test appointment` never runs them. Probes print
what they observe and never assert; they are evidence, not gates. Nothing here widens the incident fix.

- Script: `probe_related_risks.py`
- Output: `probe-output.txt` (captured on the fix commit noted inside the file)

## Command

```bash
export DJANGO_SETTINGS_MODULE=appointments.demo_settings
.venv/bin/python manage.py test demo/evidence/INC-2 --pattern="probe_*.py" -v 2
```

## Results

See `probe-output.txt` and the
[incident report](../../../docs/incidents/INC-2-stale-reschedule-confirmation.md) for classification.
SQLite serialises writes, so no concurrency or race-condition claim is made from these runs.
