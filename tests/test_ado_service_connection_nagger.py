import datetime
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock


SCRIPT_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "scripts"
    / "ado-service-connection-nagger.py"
)
SPEC = importlib.util.spec_from_file_location("ado_service_connection_nagger", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ServiceConnectionNaggerTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "identity_type": "ServicePrincipal",
            "replacement_identity_type": "ManagedIdentity",
            "replacement_identity_name_suffix": "-WIF-mi",
            "replacement_name_suffix": "-WIF",
            "date_deadline": datetime.date(2026, 11, 30),
        }
        self.identity_info = {
            "identity_type": "ServicePrincipal",
            "identity_name": "legacy",
        }
        self.replacement_endpoint = {"name": "legacy-connection-WIF"}
        self.replacement_identity_info = {
            "identity_type": "ManagedIdentity",
            "identity_name": "legacy-WIF-mi",
        }

    def test_load_config_returns_matching_connection(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as config_file:
            config_file.write(
                "service_connections:\n"
                "  legacy:\n"
                "    identity_type: ServicePrincipal\n"
                "    replacement_identity_type: ManagedIdentity\n"
                "    replacement_identity_name_suffix: -WIF-mi\n"
                "    replacement_name_suffix: -WIF\n"
                "    date_deadline: '2026-11-30'\n"
            )
            config_file.flush()

            result = MODULE.load_service_connection_config(config_file.name, "legacy")

        self.assertEqual(result["replacement_name_suffix"], "-WIF")
        self.assertEqual(result["replacement_identity_name_suffix"], "-WIF-mi")
        self.assertEqual(result["date_deadline"], datetime.date(2026, 11, 30))

    def test_load_config_returns_none_for_unmapped_connection(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as config_file:
            config_file.write("service_connections: {}\n")
            config_file.flush()

            result = MODULE.load_service_connection_config(config_file.name, "other")

        self.assertIsNone(result)

    def test_get_github_slack_user_mapping_returns_user_id(self):
        mappings = {
            "users": [
                {"github": "alice", "slack": "U123"},
                {"github": "bob", "slack": "U456"},
            ]
        }
        self.assertEqual(MODULE.get_github_slack_user_mapping(mappings, "alice"), "U123")

    def test_get_github_slack_user_mapping_returns_none_when_unmapped(self):
        self.assertIsNone(
            MODULE.get_github_slack_user_mapping({"users": []}, "unknown")
        )

    @mock.patch.object(MODULE, "get_service_principal_info")
    @mock.patch.object(MODULE.subprocess, "run")
    def test_get_current_identity_info_reads_authenticated_service_principal(
        self, run, get_info
    ):
        get_info.return_value = {
            "identity_type": "ServicePrincipal",
            "identity_name": "legacy",
        }
        run.return_value = mock.Mock(
            stdout=json.dumps({"user": {"type": "servicePrincipal", "name": "client-id"}})
        )

        result = MODULE.get_current_identity_info()

        self.assertEqual(result["identity_type"], "ServicePrincipal")
        get_info.assert_called_once_with("client-id")

    def test_normalize_application_type_to_service_principal(self):
        self.assertEqual(MODULE.normalize_identity_type("Application"), "ServicePrincipal")

    @mock.patch.object(MODULE, "get_service_principal_info")
    def test_get_endpoint_identity_info_uses_endpoint_client_id(self, get_info):
        get_info.return_value = {
            "identity_type": "ManagedIdentity",
            "identity_name": "legacy-WIF-mi",
        }
        result = MODULE.get_endpoint_identity_info(
            {
                "name": "legacy-WIF",
                "authorization": {
                    "parameters": {"serviceprincipalid": "client-id"}
                },
            }
        )

        self.assertEqual(result["identity_type"], "ManagedIdentity")
        get_info.assert_called_once_with("client-id")

    @mock.patch.object(MODULE, "urlopen")
    def test_get_service_endpoint_matches_exact_endpoint_name(self, urlopen):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "value": [
                    {"name": "legacy-connection-WIF", "id": "matching"},
                    {"name": "legacy-connection-WIF-extra", "id": "other"},
                ]
            }
        ).encode()
        urlopen.return_value = response

        result = MODULE.get_service_endpoint(
            "legacy-connection-WIF",
            "https://dev.azure.com/org/",
            "project name",
            "token",
        )

        self.assertEqual(result["id"], "matching")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer token")

    @mock.patch.object(MODULE, "notify_slack")
    @mock.patch.object(MODULE, "log_pipeline_issue")
    def test_service_principal_identity_does_not_match_map_noops(self, log_issue, notify):
        identity = {"identity_type": "ManagedIdentity", "identity_name": "other"}
        result = MODULE.check_service_connection(
            "legacy-connection",
            self.config,
            identity,
            None,
            None,
            datetime.date(2026, 11, 1),
            "webhook",
            "repo",
            "build-url",
            "alice",
        )

        self.assertEqual(result, 0)
        log_issue.assert_not_called()
        notify.assert_not_called()

    @mock.patch.object(MODULE, "notify_slack")
    @mock.patch.object(MODULE, "log_pipeline_issue")
    def test_missing_replacement_connection_noops(self, log_issue, notify):
        result = MODULE.check_service_connection(
            "legacy-connection",
            self.config,
            self.identity_info,
            None,
            None,
            datetime.date(2026, 11, 1),
            "webhook",
            "repo",
            "build-url",
            "alice",
        )

        self.assertEqual(result, 0)
        log_issue.assert_not_called()
        notify.assert_not_called()

    @mock.patch.object(MODULE, "notify_slack")
    @mock.patch.object(MODULE, "log_pipeline_issue")
    def test_wrong_replacement_identity_type_noops(self, log_issue, notify):
        replacement_identity = {
            "identity_type": "ServicePrincipal",
            "identity_name": "legacy-WIF-mi",
        }
        result = MODULE.check_service_connection(
            "legacy-connection",
            self.config,
            self.identity_info,
            self.replacement_endpoint,
            replacement_identity,
            datetime.date(2026, 11, 1),
            "webhook",
            "repo",
            "build-url",
            "alice",
        )

        self.assertEqual(result, 0)
        log_issue.assert_not_called()
        notify.assert_not_called()

    @mock.patch.object(MODULE, "notify_slack")
    @mock.patch.object(MODULE, "log_pipeline_issue")
    def test_wrong_replacement_identity_name_suffix_noops(self, log_issue, notify):
        replacement_identity = {
            "identity_type": "ManagedIdentity",
            "identity_name": "legacy-wrong-suffix",
        }
        result = MODULE.check_service_connection(
            "legacy-connection",
            self.config,
            self.identity_info,
            self.replacement_endpoint,
            replacement_identity,
            datetime.date(2026, 11, 1),
            "webhook",
            "repo",
            "build-url",
            "alice",
        )

        self.assertEqual(result, 0)
        log_issue.assert_not_called()
        notify.assert_not_called()

    @mock.patch.object(MODULE, "notify_slack")
    @mock.patch.object(MODULE, "log_pipeline_issue")
    def test_all_match_warns_on_deadline_date(self, log_issue, notify):
        result = MODULE.check_service_connection(
            "legacy-connection",
            self.config,
            self.identity_info,
            self.replacement_endpoint,
            self.replacement_identity_info,
            datetime.date(2026, 11, 30),
            "webhook",
            "repo",
            "build-url",
            "alice",
        )

        self.assertEqual(result, 0)
        self.assertEqual(log_issue.call_args.args[0], "warning")
        notify.assert_called_once()

    @mock.patch.object(MODULE, "notify_slack")
    @mock.patch.object(MODULE, "log_pipeline_issue")
    def test_all_match_warns_without_slack_when_disabled(self, log_issue, notify):
        result = MODULE.check_service_connection(
            "legacy-connection",
            self.config,
            self.identity_info,
            self.replacement_endpoint,
            self.replacement_identity_info,
            datetime.date(2026, 11, 30),
            "webhook",
            "repo",
            "build-url",
            "alice",
            slack_notifications_enabled=False,
        )

        self.assertEqual(result, 0)
        self.assertEqual(log_issue.call_args.args[0], "warning")
        notify.assert_not_called()

    @mock.patch.object(MODULE, "notify_slack")
    @mock.patch.object(MODULE, "log_pipeline_issue")
    def test_all_match_fails_after_deadline(self, log_issue, notify):
        result = MODULE.check_service_connection(
            "legacy-connection",
            self.config,
            self.identity_info,
            self.replacement_endpoint,
            self.replacement_identity_info,
            datetime.date(2026, 12, 1),
            "webhook",
            "repo",
            "build-url",
            "alice",
        )

        self.assertEqual(result, 1)
        self.assertEqual(log_issue.call_args.args[0], "error")
        notify.assert_called_once()

    @mock.patch.object(MODULE, "send_slack_message")
    @mock.patch.object(MODULE, "get_hmcts_github_slack_user_mappings")
    @mock.patch.object(MODULE, "log_pipeline_issue")
    def test_deprecated_connection_warns_if_slack_webhook_missing(
        self, log_issue, get_mappings, send_slack
    ):
        MODULE.notify_slack(None, "alice", "deprecated")
        log_issue.assert_called_once()
        self.assertIn("Missing slack webhook URL", log_issue.call_args.args[1])
        get_mappings.assert_not_called()
        send_slack.assert_not_called()

    @mock.patch.object(MODULE, "send_slack_message")
    @mock.patch.object(MODULE, "get_hmcts_github_slack_user_mappings")
    def test_notice_is_sent_to_mapped_user(self, get_mappings, send_slack):
        get_mappings.return_value = {"users": [{"github": "alice", "slack": "U123"}]}
        MODULE.notify_slack("webhook", "alice", "deprecated")
        send_slack.assert_called_once_with("webhook", "U123", "deprecated")

    @mock.patch.object(MODULE, "send_slack_message")
    @mock.patch.object(MODULE, "get_hmcts_github_slack_user_mappings")
    @mock.patch.object(MODULE, "log_pipeline_issue")
    def test_unmapped_user_gets_warning_without_slack_message(
        self, log_issue, get_mappings, send_slack
    ):
        get_mappings.return_value = {"users": []}
        MODULE.notify_slack("webhook", "alice", "deprecated")
        log_issue.assert_called_once()
        self.assertIn("does not have an entry", log_issue.call_args.args[1])
        send_slack.assert_not_called()

    @mock.patch.object(MODULE, "send_slack_message")
    @mock.patch.object(MODULE, "get_hmcts_github_slack_user_mappings")
    def test_bot_author_does_not_receive_slack_message(self, get_mappings, send_slack):
        get_mappings.return_value = {"users": [{"github": "bot", "slack": "iamabotuser"}]}
        MODULE.notify_slack("webhook", "bot", "deprecated")
        send_slack.assert_not_called()


if __name__ == "__main__":
    unittest.main()
