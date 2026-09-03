# /fathom-sync

Manually trigger the Fathom pipeline: pull new completed meetings into `wiki/meetings/`, ingest them (plus anything new in `wiki/raw/`) into the wiki, and, if a Monday token is configured, push the action items assigned to you to the Monday group named in `rekall.toml`.

## Usage

```
/fathom-sync [hours]
```

- `/fathom-sync` — process the last 26 hours (default)
- `/fathom-sync 72` — process the last 72 hours

## What This Command Does

Run the pipeline trigger script and report the result:

```bash
bash __REPO__/scripts/run-fathom-pipeline.sh --hours {hours:-26}
```

The script is idempotent — already-processed meetings (tracked in `~/.config/rekall/fathom-pipeline-state.json`) are skipped, so running it twice is safe.

After it finishes, summarize: how many new meetings were processed, which notes were written, how many action items went to Monday (or that the push was skipped), and whether the wiki ingest batches succeeded. Ingest logs live in `~/.config/rekall/logs/`.

If it fails: SSL errors mean the corporate CA bundle at `~/.config/rekall/ca-bundle.pem` needs building or rebuilding (see the corporate-CA note in `SETUP.md`); a missing-secret error means `.env` at the repo root has no `FATHOM_API_KEY`.

The scheduled version of this same script runs hourly 7am-7pm via launchd (`com.rekall.fathom-pipeline`).
