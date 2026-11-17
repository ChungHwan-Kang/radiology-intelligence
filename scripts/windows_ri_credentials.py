"""RI provider credentials in the current Windows user's credential vault."""

import base64
import ctypes
from ctypes import wintypes
import getpass
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import sys
from time import monotonic
from urllib.parse import parse_qs, urlencode, urlsplit
import warnings
import webbrowser

from native_provider_writeback import DRIVE_FOLDER, HANDOFF_DOC, NOTION_PAGE, SHEET_ID, NativeHTTP


GOOGLE_ENTRY = "RadiologyIntelligence/GoogleDesktop"
NOTION_ENTRY = "RadiologyIntelligence/NotionInternal"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/drive.file"
GOOGLE_FILES = (SHEET_ID, DRIVE_FOLDER, HANDOFF_DOC)
TOKEN_URL = "https://oauth2.googleapis.com/token"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
MAX_BLOB = 2560


class CredentialError(ValueError):
    """Errors exposed to the CLI contain fixed diagnostic codes only."""


class Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
    ]


class WindowsVault:
    def __init__(self):
        if sys.platform != "win32":
            raise CredentialError("WINDOWS_CREDENTIAL_MANAGER_UNAVAILABLE")
        dll = ctypes.WinDLL("Advapi32", use_last_error=True)
        pointer = ctypes.POINTER(Credential)
        self.read_entry = dll.CredReadW
        self.read_entry.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pointer)]
        self.read_entry.restype = wintypes.BOOL
        self.write_entry = dll.CredWriteW
        self.write_entry.argtypes = [pointer, wintypes.DWORD]
        self.write_entry.restype = wintypes.BOOL
        self.free = dll.CredFree
        self.free.argtypes = [ctypes.c_void_p]
        self.free.restype = None

    def read(self, target):
        entry = ctypes.POINTER(Credential)()
        if not self.read_entry(target, CRED_TYPE_GENERIC, 0, ctypes.byref(entry)):
            if ctypes.get_last_error() == ERROR_NOT_FOUND:
                return None
            raise CredentialError("WINDOWS_CREDENTIAL_READ_FAILED")
        try:
            size = entry.contents.CredentialBlobSize
            if not 0 < size <= MAX_BLOB or not entry.contents.CredentialBlob:
                raise CredentialError("WINDOWS_CREDENTIAL_INVALID")
            return ctypes.string_at(entry.contents.CredentialBlob, size).decode("utf-8")
        except UnicodeError:
            raise CredentialError("WINDOWS_CREDENTIAL_INVALID") from None
        finally:
            self.free(entry)

    def write(self, target, value):
        data = value.encode("utf-8")
        if not 0 < len(data) <= MAX_BLOB:
            raise CredentialError("WINDOWS_CREDENTIAL_SIZE_INVALID")
        blob = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        entry = Credential(
            Type=CRED_TYPE_GENERIC, TargetName=target, CredentialBlobSize=len(data),
            CredentialBlob=blob, Persist=CRED_PERSIST_LOCAL_MACHINE,
        )
        try:
            if not self.write_entry(ctypes.byref(entry), 0):
                raise CredentialError("WINDOWS_CREDENTIAL_WRITE_FAILED")
        finally:
            ctypes.memset(blob, 0, len(data))


def token_exchange(fields, *, request=None):
    request = request or NativeHTTP._request
    try:
        status, response = request(
            "POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"},
            urlencode(fields).encode("ascii"),
        )
    except (ValueError, OSError):
        raise CredentialError("GOOGLE_TOKEN_ENDPOINT_UNAVAILABLE") from None
    if not isinstance(response, dict):
        raise CredentialError("GOOGLE_TOKEN_RESPONSE_INVALID")
    if status in (400, 401) and fields["grant_type"] == "refresh_token":
        raise CredentialError("GOOGLE_REAUTHORIZATION_REQUIRED")
    token = response.get("access_token")
    if status != 200 or not isinstance(token, str) or not token.strip():
        raise CredentialError("GOOGLE_TOKEN_EXCHANGE_FAILED")
    return response


def refresh_google(saved, *, request=None):
    try:
        grant = json.loads(saved)
    except (TypeError, ValueError):
        raise CredentialError("GOOGLE_STORED_GRANT_INVALID") from None
    if not isinstance(grant, dict) or grant.get("scope") != GOOGLE_SCOPE:
        raise CredentialError("GOOGLE_STORED_SCOPE_MISMATCH")
    keys = ("client_id", "client_secret", "refresh_token")
    if any(not isinstance(grant.get(key), str) or not grant[key].strip() for key in keys):
        raise CredentialError("GOOGLE_STORED_GRANT_INVALID")
    response = token_exchange(
        {"grant_type": "refresh_token", **{key: grant[key] for key in keys}}, request=request,
    )
    scope = response.get("scope", GOOGLE_SCOPE)
    if not isinstance(scope, str) or set(scope.split()) != {GOOGLE_SCOPE}:
        raise CredentialError("GOOGLE_SCOPE_MISMATCH")
    return response["access_token"]


def provider_token(service, supplied):
    if supplied:
        return supplied
    if sys.platform != "win32":
        raise CredentialError(f"{service.upper()}_CREDENTIAL_NOT_ENROLLED")
    saved = WindowsVault().read(GOOGLE_ENTRY if service == "google" else NOTION_ENTRY)
    if not saved:
        raise CredentialError(f"{service.upper()}_CREDENTIAL_NOT_ENROLLED")
    return refresh_google(saved) if service == "google" else saved


def desktop_client(path):
    path = Path(path).resolve(strict=True)
    if any((parent / ".git").exists() for parent in path.parents):
        raise CredentialError("GOOGLE_CLIENT_FILE_MUST_BE_OUTSIDE_GIT")
    try:
        installed = json.loads(path.read_bytes())["installed"]
    except (ValueError, KeyError, TypeError):
        raise CredentialError("GOOGLE_DESKTOP_CLIENT_REQUIRED") from None
    if (not isinstance(installed, dict) or installed.get("project_id") != "radiology-intelligence"
            or any(not isinstance(installed.get(k), str) or not installed[k].strip()
                   for k in ("client_id", "client_secret"))):
        raise CredentialError("GOOGLE_RI_DESKTOP_CLIENT_REQUIRED")
    return {key: installed[key] for key in ("client_id", "client_secret")}


def google_consent(client):
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    callback = {}

    class Callback(BaseHTTPRequestHandler):
        timeout = 5

        def log_message(self, *_):
            pass

        def do_GET(self):
            url = urlsplit(self.path)
            params = parse_qs(url.query)
            if url.path != "/" or params.get("state") != [state]:
                self.send_error(400, "Unexpected OAuth callback")
                return
            callback.update(params)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(b"Return to the RI terminal for the result.")

    class LoopbackServer(HTTPServer):
        def handle_error(self, *_):
            pass

    with LoopbackServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}/"
        params = {
            "client_id": client["client_id"], "redirect_uri": redirect,
            "response_type": "code", "scope": GOOGLE_SCOPE, "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
            "access_type": "offline", "prompt": "consent", "trigger_onepick": "true",
            "allow_multiple": "true", "allow_folder_selection": "true",
            "file_ids": ",".join(GOOGLE_FILES),
        }
        if not webbrowser.open("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)):
            raise CredentialError("GOOGLE_BROWSER_OPEN_FAILED")
        deadline = monotonic() + 600
        while not callback and monotonic() < deadline:
            server.handle_request()
    codes = callback.get("code", [])
    if len(codes) != 1 or "error" in callback:
        raise CredentialError("GOOGLE_CONSENT_NOT_COMPLETED")
    picked = callback.get("picked_file_ids", [])
    if len(picked) != 1 or set(picked[0].split(",")) != set(GOOGLE_FILES):
        raise CredentialError("GOOGLE_PICKER_TARGETS_MISMATCH")
    response = token_exchange({
        **client, "redirect_uri": redirect, "code_verifier": verifier,
        "code": codes[0], "grant_type": "authorization_code",
    })
    scope = response.get("scope")
    if not isinstance(scope, str) or set(scope.split()) != {GOOGLE_SCOPE}:
        raise CredentialError("GOOGLE_SCOPE_MISMATCH")
    refresh = response.get("refresh_token")
    if not isinstance(refresh, str) or not refresh.strip():
        raise CredentialError("GOOGLE_REFRESH_TOKEN_NOT_RETURNED")
    return json.dumps({**client, "scope": GOOGLE_SCOPE, "refresh_token": refresh})


def enroll_google(path):
    vault = WindowsVault()
    grant = google_consent(desktop_client(path))
    vault.write(GOOGLE_ENTRY, grant)
    print("GOOGLE_ENROLLED")


def enroll_notion():
    vault = WindowsVault()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            token = getpass.getpass("Existing RI Notion connection token (hidden): ").strip()
    except (getpass.GetPassWarning, EOFError):
        raise CredentialError("NOTION_HIDDEN_INPUT_UNAVAILABLE") from None
    if not token:
        raise CredentialError("NOTION_CREDENTIAL_NOT_ENROLLED")
    try:
        status, page = NativeHTTP._request("GET", f"https://api.notion.com/v1/pages/{NOTION_PAGE}", {
            "Authorization": "Bearer " + token, "Notion-Version": "2022-06-28",
        }, None)
    except (ValueError, OSError):
        raise CredentialError("NOTION_TARGET_READ_FAILED") from None
    if (status != 200 or not isinstance(page, dict)
            or str(page.get("id", "")).replace("-", "") != NOTION_PAGE.replace("-", "")):
        raise CredentialError("NOTION_TARGET_READ_FAILED")
    vault.write(NOTION_ENTRY, token)
    print("NOTION_ENROLLED")
