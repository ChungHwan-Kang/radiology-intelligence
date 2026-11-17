import contextlib
import io
import json
import os
from pathlib import Path
import sys
from threading import Thread
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import windows_ri_credentials as credentials
import windows_ri_release as launcher


class WindowsCredentialTests(unittest.TestCase):
    def setUp(self):
        self.grant = json.dumps({
            "client_id": "fixture-client", "client_secret": "fixture-secret",
            "refresh_token": "fixture-refresh", "scope": credentials.GOOGLE_SCOPE,
        })

    def test_refresh_uses_existing_client_and_keeps_access_token_in_memory(self):
        request = Mock(return_value=(200, {"access_token": "fixture-access"}))
        self.assertEqual(credentials.refresh_google(self.grant, request=request), "fixture-access")
        method, url, _, body = request.call_args.args
        self.assertEqual((method, url), ("POST", credentials.TOKEN_URL))
        self.assertEqual(parse_qs(body.decode()), {
            "client_id": ["fixture-client"], "client_secret": ["fixture-secret"],
            "refresh_token": ["fixture-refresh"], "grant_type": ["refresh_token"],
        })

    def test_refresh_stops_on_revocation_or_scope_change(self):
        for response, error in (
            ((400, {}), "GOOGLE_REAUTHORIZATION_REQUIRED"),
            ((200, {"access_token": "fixture-access", "scope": "other-scope"}), "GOOGLE_SCOPE_MISMATCH"),
        ):
            with self.subTest(error=error), self.assertRaisesRegex(credentials.CredentialError, error):
                credentials.refresh_google(self.grant, request=Mock(return_value=response))

    def test_vault_reads_allow_reuse_without_environment_or_enrollment(self):
        vault = Mock()
        vault.read.side_effect = {
            credentials.GOOGLE_ENTRY: self.grant, credentials.NOTION_ENTRY: "fixture-notion",
        }.__getitem__
        with patch.object(credentials.sys, "platform", "win32"), patch.object(
            credentials, "WindowsVault", return_value=vault,
        ), patch.object(credentials.NativeHTTP, "_request", return_value=(200, {"access_token": "fixture-access"})):
            self.assertEqual(credentials.provider_token("google", None), "fixture-access")
            self.assertEqual(credentials.provider_token("notion", None), "fixture-notion")
            self.assertEqual(credentials.provider_token("notion", "explicit-fixture"), "explicit-fixture")
        self.assertEqual(vault.read.call_count, 2)
        vault.write.assert_not_called()

    def test_google_picker_requires_exact_targets_before_exchanging_code(self):
        client = {"client_id": "fixture-client", "client_secret": "fixture-secret"}
        for selected in (credentials.GOOGLE_FILES[:-1], credentials.GOOGLE_FILES):
            callbacks = []

            def open_browser(url):
                params = parse_qs(urlsplit(url).query)
                self.assertEqual(params["scope"], [credentials.GOOGLE_SCOPE])
                self.assertEqual(params["code_challenge_method"], ["S256"])
                query = urlencode({
                    "state": params["state"][0], "code": "fixture-code",
                    "picked_file_ids": ",".join(selected),
                })
                def send():
                    with urlopen(params["redirect_uri"][0] + "?" + query, timeout=5) as result:
                        result.read()
                worker = Thread(target=send)
                worker.start()
                callbacks.append(worker)
                return True

            response = {
                "scope": credentials.GOOGLE_SCOPE,
                "access_token": "fixture-access", "refresh_token": "fixture-refresh",
            }
            with patch.object(credentials.webbrowser, "open", side_effect=open_browser), patch.object(
                credentials, "token_exchange", return_value=response,
            ) as exchange:
                try:
                    if selected == credentials.GOOGLE_FILES:
                        saved = json.loads(credentials.google_consent(client))
                        self.assertEqual(saved["refresh_token"], "fixture-refresh")
                        self.assertNotIn("access_token", saved)
                        exchange.assert_called_once()
                    else:
                        with self.assertRaisesRegex(credentials.CredentialError, "GOOGLE_PICKER_TARGETS_MISMATCH"):
                            credentials.google_consent(client)
                        exchange.assert_not_called()
                finally:
                    for worker in callbacks:
                        worker.join(timeout=5)

    def test_notion_enrollment_rejects_wrong_page_before_saving(self):
        with patch.object(credentials, "WindowsVault") as vault, patch.object(
            credentials.getpass, "getpass", return_value="fixture-notion",
        ), patch.object(credentials.NativeHTTP, "_request", return_value=(200, {"id": "other-page"})):
            with self.assertRaisesRegex(credentials.CredentialError, "NOTION_TARGET_READ_FAILED"):
                credentials.enroll_notion()
            vault.return_value.write.assert_not_called()

    def test_check_reads_only_targets_and_reports_provider_failures_without_secrets(self):
        targets = (credentials.SHEET_ID, credentials.DRIVE_FOLDER, credentials.HANDOFF_DOC)
        responses = [
            {"spreadsheetId": targets[0]}, {"id": targets[1]}, {"documentId": targets[2]},
            ValueError("NOTION_HTTP_401"),
        ]
        with patch.dict(os.environ, {}, clear=True), patch.object(
            launcher, "GitHubContentsAdapter",
        ), patch.object(launcher, "provider_token", side_effect=["fixture-google", "fixture-notion"]), patch.object(
            launcher, "NativeHTTP",
        ) as http, contextlib.redirect_stdout(io.StringIO()) as out:
            http.return_value.call.side_effect = responses
            self.assertEqual(launcher.check_connections(), 1)
            self.assertTrue(all(call.args[1] == "GET" for call in http.return_value.call.call_args_list))
        self.assertIn("SHEETS_READ PASS", out.getvalue())
        self.assertIn("NOTION_READ BLOCKED CREDENTIAL_REAUTHORIZATION_REQUIRED", out.getvalue())
        self.assertNotIn("fixture", out.getvalue())

    def test_check_reports_missing_provider_without_reconsent(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            launcher, "GitHubContentsAdapter",
        ), patch.object(
            launcher, "provider_token",
            side_effect=[credentials.CredentialError("GOOGLE_CREDENTIAL_NOT_ENROLLED"), "fixture-notion"],
        ), patch.object(launcher, "NativeHTTP") as http, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(launcher.check_connections(), 1)
        self.assertIn("GOOGLE_AUTH BLOCKED GOOGLE_CREDENTIAL_NOT_ENROLLED", out.getvalue())
        self.assertNotIn("NOTION_AUTH BLOCKED", out.getvalue())
        http.assert_not_called()

    def test_release_requires_receipt_before_vault_access(self):
        with patch.object(
            launcher, "read_inputs", side_effect=ValueError("ARTICLE_APPROVAL_EVENT_REQUIRED"),
        ), patch.object(launcher, "provider_token") as provider_token:
            with self.assertRaisesRegex(ValueError, "ARTICLE_APPROVAL_EVENT_REQUIRED"):
                launcher.run_release(object())
        provider_token.assert_not_called()
