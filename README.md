# apkpatcher-bot

Telegram bot wrapping the [ApkPatcher](https://pypi.org/project/ApkPatcherX/)
CLI, running entirely on GitHub Actions with a local Telegram Bot API server
(files up to ~2 GB in both directions).

## How it runs

- `.github/workflows/bot.yml` — the main loop. Each cycle runs the bot for
  ~5h50m, then gracefully stops; the next cycle is chained automatically via
  the `workflow_run` event, with a 6-hour cron as a backup.
- `.github/workflows/test-suite.yml` — manual run of the 23-case verification
  suite for every tool/flag (`tools_test.py`).

## Configuration (repository secrets)

| Secret | Purpose |
| --- | --- |
| `BOT_TOKEN` | Telegram bot token |
| `API_ID` / `API_HASH` | credentials for the local Bot API server |
| `ALLOWED_USERS` | comma-separated Telegram user IDs allowed to use the bot |

No secrets are stored in the code; the repository itself is public.
