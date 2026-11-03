# Incidents

Synthetic scheduling incident reports from rehearsals on this fork. They use synthetic data only and make no
production or NHS claims.

| Incident | Summary | Base | PR |
| --- | --- | --- | --- |
| [INC-2](INC-2-stale-reschedule-confirmation-blocked-hour.md) | Stale reschedule confirmation accepts a newly blocked hour; confirmation now re-checks `Unavailability` and returns 409 | `demo/ready` @ `757f2517` | [#10](https://github.com/raffimaurer/django-appointment/pull/10) |
