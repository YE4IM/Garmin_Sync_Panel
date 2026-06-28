from __future__ import annotations

import argparse
import getpass
import json

import uvicorn

from .auth import hash_local_password
from .config import settings
from .microsoft_graph_mail import MicrosoftGraphAuthError, authorize_with_device_code, token_status
from .reporting import generate_report, send_report_email
from .sync_runner import SyncRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Garmin Sync unified service")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="start the web service")
    sub.add_parser("run-daily", help="run sync, generate report, and send email")
    sync_parser = sub.add_parser("sync", help="run Garmin/Xiaomi sync only")
    sync_parser.add_argument("--days", type=int, default=None, help="override activity and health backfill days for this run")
    sub.add_parser("report", help="generate readable report attachments and send email")
    sub.add_parser("auth-microsoft", help="authorize Microsoft Graph Mail.Send using device code flow")
    sub.add_parser("mail-status", help="show Microsoft Graph mail authorization status")
    sub.add_parser("hash-password", help="generate LOCAL_AUTH_PASSWORD_HASH for local login")
    args = parser.parse_args()

    runner = SyncRunner(settings)
    if args.command == "serve":
        uvicorn.run("garmin_sync_service.web:app", host="127.0.0.1", port=3020, reload=False)
        return 0
    if args.command == "sync":
        run_settings = settings
        if args.days:
            run_settings = settings.__class__(**{
                **settings.__dict__,
                "sync_activity_days": args.days,
                "sync_health_days": args.days,
            })
            runner = SyncRunner(run_settings)
        print(json.dumps(runner.run_all(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "report":
        report = generate_report(settings, runner.last_run())
        mail = send_report_email(settings, report)
        print(json.dumps({"report": report, "mail": mail}, ensure_ascii=False, indent=2))
        return 0 if mail.get("ok") or mail.get("skipped") else 1
    if args.command == "auth-microsoft":
        try:
            print(json.dumps(authorize_with_device_code(settings), ensure_ascii=False, indent=2))
            return 0
        except MicrosoftGraphAuthError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
    if args.command == "mail-status":
        print(json.dumps({"provider": settings.mail_provider, "microsoftGraph": token_status(settings)}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "hash-password":
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm: ")
        if password != confirm:
            print("Passwords do not match")
            return 1
        print(hash_local_password(password))
        return 0
    if args.command == "run-daily":
        sync_result = runner.run_all()
        report = generate_report(settings, sync_result)
        mail = send_report_email(settings, report)
        print(json.dumps({"sync": sync_result, "report": report, "mail": mail}, ensure_ascii=False, indent=2))
        return 0 if sync_result.get("ok") and (mail.get("ok") or mail.get("skipped")) else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
