# INC-8 deleted-appointment probe evidence

> Synthetic data only. This is evidence, not part of the normal test suite. No existing tests are changed, and no confirmation IDs or link URLs are recorded.

## What this shows

`probe_deleted_appointment.py` contains one probe for the issue symptom and two related-risk probes. Each probe prints an `OBSERVED` line
and then asserts the desired behaviour, so a failing probe is evidence of a defect.

| Probe | Scenario | Before fix (`47a7917`, `demo/stable`) | After fix (`de786f0`) | Classification |
|---|---|---|---|---|
| `test_issue_confirm_after_appointment_deleted` | `Appointment` deleted while its reschedule is pending, then link opened | 500; request moved; history `confirmed`; 0 notifications (**FAIL**) | 404; request not moved; history `pending`; 0 notifications (pass) | Reproduced, **fixed** by this PR |
| `test_related_submit_after_appointment_deleted` | `Appointment` deleted, then a reschedule is submitted for its request | 500; 1 pending history row created; 0 emails (**FAIL**) | unchanged (**FAIL**) | Reproduced, **not fixed** (out of scope) |
| `test_related_confirm_after_target_staff_deleted` | target `StaffMember` of a pending reschedule deleted, then link opened | 302; request staff set to `None`; history `confirmed`; 1 notification (**FAIL**) | unchanged (**FAIL**) | Reproduced, **not fixed** (out of scope) |

Raw output: [`probe-output-before.txt`](probe-output-before.txt) and [`probe-output-after.txt`](probe-output-after.txt).
Absolute paths in the output were shortened.

## Commit context

- Before: `demo/stable` @ `47a7917c810f3965a96f979f7f32f20b475b102b` with only the probe file added (no fix).
- After: fix commit `de786f06afd554dbe42c39308b78aad0d8b9d1cc` plus the probe file.
- Python 3.12.16, `demo-requirements.lock`, `DJANGO_SETTINGS_MODULE=appointments.demo_settings`, SQLite, locmem mail backend.
- SQLite serialises writes, so these probes say nothing about concurrent requests.

## Reproduce

```bash
export DJANGO_SETTINGS_MODULE=appointments.demo_settings
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations appointment   # output is git-ignored
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py test demo/evidence/INC-8 --pattern='probe_*.py' -v 2
# before the fix: Ran 3 tests, FAILED (failures=3)
# after the fix:  Ran 3 tests, FAILED (failures=2); the issue probe passes, the two related-risk probes still fail
```

## Why it stays out of the green suite

- `demo-verify` runs `manage.py test appointment`, which only discovers tests inside the `appointment` package.
- This directory is outside that package, has no `__init__.py`, and the file isn't named `test*.py`.
- With the probe present, `manage.py test appointment` still reports `Ran 590 tests` / `OK (skipped=3)` locally.
