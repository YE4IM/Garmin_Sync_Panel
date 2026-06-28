# Notices

This repository imports and wraps two existing local projects:

- `garmin-activity-sync`
- `garmin-weight-sync`

The imported projects' README files state MIT licensing. Keep their notices and
documentation when publishing derived work.

This project uses Garmin Connect and Xiaomi/Mi Fitness automation. It is best
suited to personal or small private deployments.

The public default login mode is local username/password auth. Private
deployments can opt into an external account provider through environment
configuration.

Runtime credentials, OAuth sessions, SQLite databases, FIT files, logs, and
generated reports are deployment data, not source files.
