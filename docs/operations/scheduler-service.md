# scheduler service

This page documents running the APScheduler entrypoint manually and as a long-running
systemd user service.

## Manual runs

Validate manifest and job registration only:

```powershell
poetry run python main.py --jobs-file config/spider_jobs.yaml --dry-run
```

Start the scheduler loop:

```powershell
poetry run python main.py --jobs-file config/spider_jobs.yaml
```

Key optional arguments:

- `--timezone` (default: `Europe/Warsaw`)
- `--log-level`
- `--json-logs` / `--no-json-logs`

## systemd user service (Linux host)

Template unit file:

- `systemd/listing-lens-scheduler.service`

Install in user service mode:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/listing-lens-scheduler.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now listing-lens-scheduler.service
```

Before enabling:

- Update `WorkingDirectory` to your checkout path.
- Update `EnvironmentFile` to your `.env` location.
- Update `ExecStart` if Poetry is installed in a different path.

## Logs and troubleshooting

- App logs are written to `logs/`.
- Use `journalctl --user -u listing-lens-scheduler.service -f` for service logs.
- If jobs do not run, validate `config/spider_jobs.yaml` first with `--dry-run`.
