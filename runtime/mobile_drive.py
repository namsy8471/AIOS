"""Google Drive authorization and explicit file export from the Windows worker."""
import argparse
from base64 import b64decode, b64encode
import json
import os
from pathlib import Path
import secrets
import subprocess
from urllib.request import Request, urlopen

from mobile_cloud import AccountRequired


SCOPE = "https://www.googleapis.com/auth/drive.file"
STORAGE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AIOS" / "google-drive.dpapi"
DPAPI = Path(__file__).resolve().parent.parent / "scripts/mobile-credential.ps1"


def protect(operation, data):
    process = subprocess.run(["pwsh.exe", "-NoProfile", "-NonInteractive", "-File", str(DPAPI), operation],
                             input=b64encode(data), capture_output=True, check=True, timeout=15)
    return b64decode(process.stdout, validate=True)


def save_credentials(credentials):
    encrypted = protect("protect", credentials.to_json().encode())
    STORAGE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STORAGE.with_name(f"drive-{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_bytes(encrypted)
        temporary.replace(STORAGE)
    finally:
        temporary.unlink(missing_ok=True)


def access_token():
    if not STORAGE.exists():
        raise AccountRequired("Connect Google Drive on the Windows PC")
    try:
        from google.auth.transport.requests import Request as RefreshRequest
        from google.oauth2.credentials import Credentials
        from google.auth.exceptions import GoogleAuthError
    except ImportError as error:
        raise AccountRequired("Install the optional Google Drive OAuth dependencies on the Windows PC") from error
    credentials = Credentials.from_authorized_user_info(json.loads(protect("unprotect", STORAGE.read_bytes())), [SCOPE])
    if not credentials.valid:
        try:
            credentials.refresh(RefreshRequest())
        except GoogleAuthError as error:
            raise AccountRequired("Reconnect Google Drive on the Windows PC") from error
        save_credentials(credentials)
    return credentials.token


def upload_draft(name, text):
    token = access_token()
    boundary = "aios-" + secrets.token_hex(16)
    metadata = json.dumps({"name": name, "mimeType": "text/markdown"}, ensure_ascii=False)
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{metadata}\r\n"
            f"--{boundary}\r\nContent-Type: text/markdown; charset=UTF-8\r\n\r\n{text}\r\n--{boundary}--\r\n").encode()
    url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,webViewLink"
    request = Request(url, data=body, headers={"Authorization": f"Bearer {token}",
                                              "Content-Type": f"multipart/related; boundary={boundary}"})
    with urlopen(request, timeout=40) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("connect", "status", "disconnect"))
    parser.add_argument("--client-json", type=Path)
    args = parser.parse_args()
    if args.action == "connect":
        if args.client_json is None:
            parser.error("Google Drive requires a Google Desktop OAuth client JSON")
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(args.client_json), [SCOPE], autogenerate_code_verifier=True)
        credentials = flow.run_local_server(host="127.0.0.1", port=0, timeout_seconds=180, access_type="offline", prompt="consent")
        if not credentials.has_scopes([SCOPE]) or not credentials.refresh_token:
            raise AccountRequired("Google Drive did not grant persistent access")
        save_credentials(credentials)
    elif args.action == "disconnect":
        STORAGE.unlink(missing_ok=True)
    print(json.dumps({"connection_saved": STORAGE.exists()}))


if __name__ == "__main__":
    main()
