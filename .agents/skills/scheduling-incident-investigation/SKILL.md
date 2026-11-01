---
name: scheduling-incident-investigation
description: Reviewed, repository-shared procedure for investigating and repairing appointment booking or reschedule incidents (slot offer, hold, confirmation/commit) in django-appointment with reproducible, evidence-backed results. Use when an issue reports appointments landing in blocked, overlapping, expired or otherwise invalid time.
---

# Scheduling incident investigation

Shared guidance for booking/reschedule incidents. It describes *how* to
investigate; it does not prescribe a particular function or fix.

## 1. Pin the environment
- Record the exact base commit SHA and branch you started from.
- Use the pinned interpreter and lock file named in the repo docs (for the
  demo: Python 3.12, `demo-requirements.lock`,
  `DJANGO_SETTINGS_MODULE=appointments.demo_settings`). Note any deviation.
- Run `manage.py check`, `makemigrations appointment`, `migrate` before tests.
  Generated migrations are git-ignored; never commit them.

## 2. Reproduce before editing
- Run the issue's acceptance tests and the full suite on the unmodified base.
  Record the exact command and the `Ran N tests ... FAILED (...)` line.
- Confirm the failure matches the reported symptom. If it does not reproduce,
  stop and report; do not "fix" an unreproduced problem.

## 3. Trace the whole flow
- Follow a slot from **offer** (availability listing) through any **hold**
  (pending request, emailed link) to **commit** (confirmation that mutates the
  booking). Identify where validity is checked at each stage and which checks
  are missing or stale at commit time.
- Availability state can change between offer and commit (new unavailability,
  days off, working-hours edits, other bookings). Commit must re-validate
  against current state, not trust what was true when the offer was made.

## 4. Get interval semantics right
- Treat times as half-open intervals `[start, end)`: touching boundaries
  (one ends at 11:00, next starts at 11:00) do not overlap; partial overlaps do.
- Scope conflicts to the same staff member and the same date. A block for a
  different staff member or day must not reject the request.

## 5. Rejection must be side-effect free
- On rejection, leave the original booking and the pending request rows
  unchanged (no status flip to confirmed, no field swaps).
- Do not send notifications/emails or enqueue tasks for a rejected commit.
- Return a clear client error (e.g. 400/409) with a user-safe message.

## 6. Expiry and replay
- Check link/hold expiry and that a used or non-pending request cannot be
  confirmed again (replay). Note expiry windows when writing timing-sensitive
  tests.

## 7. Tests
- Keep existing acceptance tests unchanged; never weaken or delete assertions
  to get green. Add tests only where they cover a real, distinct behaviour
  (both the rejection and the still-allowed neighbours).
- Run the targeted tests and then the **full suite**; report real counts.

## 8. Secrets and tokens
- Never log, print, paste into PRs/issues, or commit bearer tokens,
  confirmation/reschedule IDs, password-reset tokens, or full URLs containing
  them. Redact (e.g. `/confirm/<redacted>/`).

## 9. Related-risk audit (bounded)
- Inspect sibling paths that commit time (new booking, admin edits,
  reschedule submit) for the same missing re-validation.
- Clearly separate **reproduced** (test demonstrates it) from **suspected**
  (code reading only). Do not fix suspected issues in the same change unless
  asked; list them.
- Do not make concurrency or race-condition claims from SQLite test runs;
  SQLite serialises writes. State that such risks are unverified.

## 10. Deliver
- Separate fix branch; draft PR against the stated base in the same repo.
- PR and short incident note include: base SHA, commands, before/after test
  counts, root cause, change summary, reproduced vs suspected risks, and
  anything not verified.
- Never merge, deploy, change branch protection or repository settings.
