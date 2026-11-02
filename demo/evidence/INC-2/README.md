# INC-2 sibling-defect probe evidence

> Synthetic data only. This is evidence, not part of the normal test suite. The acceptance tests are not changed.

## What this shows
The INC-2 fix (`has_overlapping_unavailability` in `confirm_reschedule`) only re-checks `Unavailability` at confirmation.
This probe checks three other availability inputs that can change while a reschedule request is pending:

| Probe | State changed after the request | Observed on `5ba62ed` | Desired |
|---|---|---|---|
| `test_control_no_change_confirms` | nothing (control) | HTTP 302, moved (ok) | 302, moved |
| `test_day_off_added_after_request` | `DayOff` covering the requested date | HTTP 302, moved (**FAIL**) | 409, not moved |
| `test_overlapping_appointment_added_after_request` | another appointment for the same staff member, same date and time | HTTP 302, moved (**FAIL**) | 409, not moved |
| `test_working_hours_changed_after_request` | `WorkingHours` added for that weekday, 13:00–17:00 only | HTTP 302, moved (**FAIL**) | 409, not moved |

The three failures are reproduced defects. They are out of scope for the INC-2 fix and are listed as follow-up 1 in the
[incident report](https://github.com/raffimaurer/django-appointment/blob/devin/1793656832-inc-2-stale-reschedule-confirmation/docs/incidents/INC-2-stale-reschedule-confirmation.md).

## Provenance
The original probe from the investigation was a throwaway test file that was deleted without being committed. **Its file and raw
output are unavailable and are not preserved here.** The investigation recorded its result as HTTP 302 for all three cases.
`probe_sibling_defects.py` is a re-creation written later at the maintainer's request. It covers the same three scenarios plus a control.
`probe-output.txt` is its actual output on PR head `5ba62ed169f000cd67b4b9c64293124a7dbe7e97` (Python 3.12.16, `demo-requirements.lock`,
`appointments.demo_settings`, SQLite). Absolute paths in the output were shortened.

## Reproduce
```bash
export DJANGO_SETTINGS_MODULE=appointments.demo_settings
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations appointment   # output is git-ignored
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py test demo/evidence/INC-2 --pattern='probe_*.py' -v 2
# expected while the defects exist: Ran 4 tests, FAILED (failures=3); the control passes
```

## Why it stays out of the green suite
- `demo-verify` runs `manage.py test appointment`, which only discovers tests inside the `appointment` package.
- The probe lives outside that package, has no `__init__.py` and isn't named `test*.py`, so default discovery skips it too.
- With the probe present, `manage.py test appointment` still reports `Ran 583 tests` / `OK (skipped=3)` locally.
