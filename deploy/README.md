# Growthrova service deployment

Production runs two systemd services:

- `growthrova-api.service` serves the private Flask API on `127.0.0.1:4190`.
- `growthrova-frontend.service` serves Next.js on `127.0.0.1:4195` and proxies Growthrova API requests to the private API.

Both services run as the dedicated `growthrova` Linux account from `/home/growthrova/app`. Runtime credentials and the SQLite database remain outside Git under `/home/growthrova`.

Install or update the units with root access, reload systemd, then restart the API before the frontend. Verify the homepage returns 200 and an unauthenticated organisation API request returns 401.

The pre-migration Clippr-owned service files and database were retained on the server as rollback material. Do not reactivate them alongside the Growthrova services because they bind the same ports.
