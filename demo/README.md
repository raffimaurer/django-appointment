# Incident demo: reschedule confirmation ignores newly blocked staff time

> **Synthetic data, real upstream defect.** All people, appointments and the
> "staff meeting" block in these tests are synthetic. There is no real customer
> or NHS affiliation. The defect itself is real behaviour of upstream
> `django-appointment` at commit `0e84577e80649e752a31b8b84acd96cfc2ec5782`;
> it is **not** an injected regression. Production source is unchanged on this
> branch.

## Scenario

1. A client requests a reschedule into a free slot. A pending
   `AppointmentRescheduleHistory` row is created and a confirmation link is
   emailed.
2. Before the client clicks the link, the staff member blocks that time
   (an `Unavailability`). The slot listing correctly hides it.
3. The client clicks the confirmation link. The appointment is moved into the
   newly blocked time and the admin is notified.

## Setup (Python 3.12, local only)

```bash
python3.12 -m venv .venv            # or: uv venv --python 3.12 .venv
.venv/bin/python -m pip install -r demo-requirements.lock
export DJANGO_SETTINGS_MODULE=appointments.demo_settings
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations appointment
.venv/bin/python manage.py migrate
```

Migrations under `appointment/migrations/` are git-ignored upstream and are
generated locally by `makemigrations`.

## Reproduce

```bash
export DJANGO_SETTINGS_MODULE=appointments.demo_settings
# Incident acceptance tests: expect 7 tests, 3 failures
.venv/bin/python manage.py test appointment.tests.test_incident_reschedule -v 2
# Full suite: expect 576 tests, 3 failures, 3 skipped
.venv/bin/python manage.py test appointment
```

## Intentionally failing assertions

`appointment/tests/test_incident_reschedule.py` defines the acceptance
criteria. On this branch these three fail by design, because they describe the
desired behaviour, not the current one:

- `test_confirmation_rejects_new_block_without_mutation` — confirming into a
  fully blocked slot must not move the appointment, must not mark the request
  confirmed, must return 400/409 and must not notify the admin.
- `test_partial_overlap_rejected` — a block that partly overlaps the new slot
  must also be rejected.
- `test_real_submit_then_block_then_confirm` — end-to-end: real reschedule
  submit, then a block, then confirmation must be rejected.

These four pass and guard against over-correction: slot listing hides the
block, unblocked confirmation still works, an adjacent block is allowed, and a
block for a different staff member is allowed.

Do not edit or weaken these tests to make them pass.

## Reschedule link expiry

`AppointmentRescheduleHistory.still_valid()` treats a pending request as valid
for 5 minutes (300 seconds) after `created_at`. The tests create the pending
request in `setUp` and confirm immediately, so they run inside that window. For
a manual demo, click the confirmation link within 5 minutes of submitting.

## Demo settings (local only)

`appointments/demo_settings.py` extends `appointments/settings.py` with:

- the existing local SQLite database (`db.sqlite3`; tests use Django's test DB),
- the in-memory (`locmem`) email backend, so no email leaves the machine,
- `USE_DJANGO_Q_FOR_EMAILS = False`,
- the fast, insecure MD5 password hasher for speed.

**Never deploy these settings.** They exist only for this local, reproducible
demo.
