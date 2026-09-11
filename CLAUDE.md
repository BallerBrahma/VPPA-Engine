# CLAUDE.md

Project guidance for Claude Code working in this repo.

## Git: never commit or push directly

When I ask you to commit or push, **do not run the command yourself**. Print the
exact command(s) for me to paste into my own terminal, then stop.

- **Never** include a `Co-Authored-By:` trailer in commit messages.
- Before handing over a push command, verify no secrets are tracked (`.env`, the
  NREL API key, `data/`).
- You may freely run read-only git commands (`git status`, `git log`, `git diff`,
  `git remote -v`) to inspect state or confirm that a command I ran worked.

## Stay inside the sandbox — don't trip endpoint security

This machine may run endpoint security / EDR software. Avoid patterns that look
like malware behavior, even when they'd be technically convenient. Concretely:

- **Stay in the project directory.** Don't read, write, move, or delete files
  elsewhere on the system. Use the scratchpad for temp files, never `/tmp`
  directly or anywhere under `~` outside this repo.
- **Don't manipulate file metadata.** No `chflags`, `chmod`, `chown`, `xattr`,
  or codesigning operations — including inside `.venv/`. If a tool's own files
  are misbehaving, diagnose it and tell me; don't reach in and change flags.
- **Don't scan for credentials.** No `env | grep -i key/token/secret`, no
  grepping the filesystem for `.env`, `.aws`, `.ssh`, keychains, or browser
  data. If you need a credential, ask me for it.
- **No install-by-pipe.** Never `curl ... | sh` or run remote scripts. Ask
  before installing anything system-wide (`brew install`, global `npm -g`,
  `pip --user`); project-local `uv` deps are fine.
- **Keep network access narrow and expected.** Only the documented data sources
  (NSRDB/NREL, ERCOT via gridstatus, EIA). No broad crawling, port scanning, or
  bulk parallel requests that look like exfiltration or a DoS.
- **No obfuscation.** No base64-encoded commands, no `eval` of downloaded
  content, nothing that hides what's actually running.
- **Never disable security tooling** or add exclusions to work around a block.
  If something is blocked, stop and tell me.

## Project

Solar VPPA settlement and basis-risk engine. See
[solar-vppa-engine-design.md](solar-vppa-engine-design.md) for the full
architecture, data sources, known traps, and build phases.

## Environment

- `uv` manages deps. `uv sync --extra dev --extra ui` to set up.
- Secrets live in `.env` (gitignored): `NREL_API_KEY`, `NREL_API_EMAIL`.
- Tests: `uv run pytest`. Lint: `uv run ruff check .`
- Ad-hoc scripts need `PYTHONPATH=src` (uv's editable-install `.pth` file keeps
  acquiring the macOS `hidden` flag, which Python 3.13's `site.py` skips).
  `pytest` is unaffected — `pythonpath = ["src"]` is set in `pyproject.toml`.

## Conventions

- The `engine/` layer stays pure: no I/O, no network. It must be testable from
  small in-memory fixtures.
- Validation belongs in `model.py`, not in the engine.
- Store all timestamps in UTC internally; convert only at display.
- Never clip negative prices — they are a central result, not bad data.
- Keep the automated test suite offline and deterministic. Verify real
  network-backed behavior with one-off manual runs instead.
