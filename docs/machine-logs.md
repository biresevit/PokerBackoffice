# Requesting logs from a fleet PC

Open **Machines > Logs** on a PC, or **Fleet > Machine logs**. Select the PC and
recent-file period, then request collection. The history shows queued,
collecting, uploading, ready, failed or expired. Ready requests have a Download
ZIP button. Operators request collection; viewers may download their customer's
existing bundles. Both operations are audited.

Local operator tooling also requests and downloads bundles without opening the
website. From PokerBackoffice:

```powershell
.\.venv\Scripts\python.exe tools\request_logs.py --machine 19 --hours 24 --subject <operator-subject> --wait-minutes 10
```

Use `--request-id <id>` to resume waiting for an existing request. Set
`BACKOFFICE_OPERATOR_SUBJECT` once to omit `--subject`; it is also optional when
the customer has exactly one active operator membership. The tool uses the
configured local database access, checks the operator membership, audits the
request/download and stores ZIPs under `artifacts/machine-logs`. Size and SHA-256
are verified before the final file is saved. Credentials and SAS links are not
printed. Archives are not automatically extracted.

## Collector and bounds

Updater 1.0.14 runs the collector independently of application readiness and
application update tasks. Existing agents can keep running: the new signed
PokerController package includes the same collector as a background helper.
The helper exits when its worker exits. A PC needs either the new updater or a
worker release containing the helper before it can process requests. Requests
remain queued while it is disconnected or still running older software.

Collection never stops poker processes or changes sessions. Allowed files are
the updater/diagnostic logs, PDecision logs under `C:\PokerSuite\Logs`, and
worker/pilot logs plus status.json in recent managed run folders. It selects
files modified during the requested 1–168 hours, includes up to 8 MiB from the
end of each file and 48 MiB total, and limits the compressed ZIP to 64 MiB.
The manifest records selected files, modification dates and truncation. A file
may contain lines older than the requested period; the period selects recent
files rather than trimming multiline log events. Locked files are read with
sharing enabled; unavailable files are listed as skipped.

Configuration, enrollment and database files are excluded. Known runtime
passwords, connection strings and enrollment tokens are removed from log text;
credential patterns and URLs containing query strings are also redacted. Path
escapes and filesystem links are rejected. Empty worker logs are fixed by
explicitly configuring logging even if an imported dependency initialized the
root logger earlier. Seat-loss reconciliation logs include observation timing
and connection readiness without exposing cards or credentials.

The API authenticates each collector with that PC's enrollment and issues a
claim tied to the request and machine. A 15-minute claim protects against two
collectors processing one request; an expired claim can be retried. The collector
gets a create/write SAS for exactly one blob, valid for 15 minutes. A ready report
checks the uploaded size and SHA-256. Authorized download links grant read-only
access for 15 minutes. Requests expire seven days after creation and Azure Blob
lifecycle management removes bundles after seven days. The storage account
signing credential stays in API configuration and never goes to PCs or browsers.

Apply migration `012_machine_logs.sql`, run `tools/configure_diagnostics.py`,
then deploy the API/frontend before distributing the signed worker and updater.
No scheduler function deployment or PDecision change is needed.
