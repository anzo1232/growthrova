# Clippr

Stream clipping + TikTok Shop ad generation. Flask backend on a Hetzner box
(`/opt/clippr`, systemd `clippr.service`), Vite/React front end on Vercel.


## Layout

- `src/` — the Vite/React front end deployed to Vercel (project `clippr-site`).
- `imagegen.py` — Shop image/video engine. Working copy; `scp` to `/opt/clippr/` to deploy.
- `patch_*.py` — anchored patch scripts applied **on the box** against the live `server.py`.
  Each asserts its anchor occurs exactly once, backs up to `.bak.<epoch>`, and is idempotent.
- `prod_snapshot/` — **one-way** mirror of the live `/opt/clippr/` files. Read-only:
  the live file is the source of truth and this must never be pushed back. See
  `prod_snapshot/README.md`.
- `server.py` (repo root) — legacy/stale copy predating the snapshot; kept for history.
  Do not treat it as current. Use `prod_snapshot/server.py.prod-snapshot`.
- `*_BRIEF.md`, `*_HANDOFF.md` — feature briefs driving each work stream.

## Secrets

Nothing in this repo carries credentials. Keys live in `/opt/clippr/.env` on the box
(loaded at process start) and in Vercel env vars for the front end. `.env*`, cookie
files, `*.pem` and `*.key` are gitignored — keep it that way.
