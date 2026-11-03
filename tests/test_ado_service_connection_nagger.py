import datetime
import importlib.util
import json
import pathlib
import re
import subprocess
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
from unittest import mock

import yaml


SCRIPT_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "scripts"
    / "ado-service-connection-nagger.py"
)
SPEC = importlib.util.spec_from_file_location("ado_service_connection_nagger", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ServiceConnectionTemplateTests(unittest.TestCase):
    def nagger_templates(self):
        root = SCRIPT_PATH.parents[1]
        for directory in ("steps", "tasks", "jobs"):
            for path in (root / directory).rglob("*.yaml"):
                text = path.read_text()
                if "service-connection-deprecation-checker.yaml" in text:
                    yield path, text, yaml.safe_load(text)

    def test_nagger_callers_only_reference_declared_parameters(self):
        for path, text, template in self.nagger_templates():
            with self.subTest(template=path):
                parameters = template.get("parameters", {})
                declared = (
                    set(parameters)
                    if isinstance(parameters, dict)
                    else {parameter["name"] for parameter in parameters}
                )
                referenced = set(re.findall(r"parameters\.([A-Za-z0-9_]+)", text))
                self.assertEqual(referenced - declared, set())

    def test_nagger_template_paths_resolve(self):
        for path, text, _ in self.nagger_templates():
            with self.subTest(template=path):
                includes = re.findall(
                    r"template:\s*(\S*service-connection-deprecation-checker\.yaml)",
                    text,
                )
                for include in includes:
                    self.assertTrue((path.parent / include).is_file(), include)


class ServiceConnectionNaggerTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "identity_type": "ServicePrincipal",
            "replacement_identity_type": "ManagedIdentity",
            "replacement_identity_name_suffix": "-WIF-mi",
            "replacements": {
                "Project name": {
                    "legacy-connection": "renamed-connection-WIF",
                    "normal": "normal-WIF",
                },
                "Other project": {"legacy-connection": "other-WIF"},
            },
            "date_deadline": datetime.date(2026, 11, 30),
        }
        self.identity_info = {
            "identity_type": "ServicePrincipal",
            "identity_name": "legacy",
        }
        self.replacement_endpoint = {"name": "renamed-connection-WIF"}
        self.replacement_identity_info = {
            "identity_type": "ManagedIdentity",
            "identity_name": "legacy-WIF-mi",
        }

    def test_load_config_returns_policies_keyed_by_identifier(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as config_file:
            config_file.write(
                "service_connections:\n"
                "  policy-id-not-ado-name:\n"
                "    identity_type: ServicePrincipal\n"
                "    replacement_identity_type: ManagedIdentity\n"
                "    replacement_identity_name_suffix: -WIF-mi\n"
                "    replacements:\n"
                "      Project name:\n"
                "        legacy-connection: renamed-connection-WIF\n"
                "    date_deadline: '2026-11-30'\n"
            )
            config_file.flush()

            result = MODULE.load_service_connection_policies(config_file.name)

        self.assertEqual(len(result), 1)
        policy_id, policy = result[0]
        self.assertEqual(policy_id, "policy-id-not-ado-name")
        self.assertEqual(
            MODULE.resolve_replacement_name(policy, "Project name", "legacy-connection"),
            "renamed-connection-WIF",
        )
        self.assertEqual(policy["replacement_identity_name_suffix"], "-WIF-mi")
        self.assertEqual(policy["date_deadline"], datetime.date(2026, 11, 30))

    def test_load_config_returns_empty_list_when_no_policies(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as config_file:
            config_file.write("service_connections: {}\n")
            config_file.flush()

            result = MODULE.load_service_connection_policies(config_file.name)

        self.assertEqual(result, [])

    def test_resolves_names_with_project_scope_and_case_insensitive_matching(self):
        for project, connection, expected in (
            ("project NAME", "LEGACY-connection", "renamed-connection-WIF"),
            ("Other project", "legacy-connection", "other-WIF"),
            ("Project name", "normal", "normal-WIF"),
        ):
            with self.subTest(project=project, connection=connection):
                self.assertEqual(
                    MODULE.resolve_replacement_name(self.config, project, connection),
                    expected,
                )

    def test_unmapped_project_or_connection_logs_and_does_not_guess(self):
        for project, connection in (
            ("Unknown project", "normal"),
            ("Project name", "unknown"),
        ):
            with self.subTest(project=project, connection=connection):
                with self.assertLogs(MODULE.logger, level="INFO") as logs:
                    self.assertIsNone(
                        MODULE.resolve_replacement_name(self.config, project, connection)
                    )
                self.assertIn("no replacement mapping exists", logs.output[0])

    def test_missing_project_context_fails_explicitly(self):
        with self.assertRaisesRegex(RuntimeError, "SYSTEM_TEAMPROJECT"):
            MODULE.resolve_replacement_name(self.config, None, "normal")

    def test_invalid_and_ambiguous_mappings_are_rejected(self):
        cases = (
            None,
            [],
            {"Project": []},
            {"Project": {"legacy": ""}},
            {"Project": {"legacy": 123}},
            {" ": {"legacy": "replacement"}},
            {"Project": {"legacy": "a"}, "PROJECT": {"legacy": "b"}},
            {"Project": {"legacy": "a", "LEGACY": "b"}},
        )
        for replacements in cases:
            with self.subTest(replacements=replacements):
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as file:
                    yaml.safe_dump(
                        {
                            "service_connections": {
                                "policy": {
                                    **self.config,
                                    "replacements": replacements,
                                }
                            }
                        },
                        file,
                    )
                    file.flush()
                    with self.assertRaises(ValueError):
                        MODULE.load_service_connection_policies(file.name)

    def test_exact_duplicate_yaml_keys_are_rejected(self):
        for replacements in (
            "      Project:\n        legacy: first\n        legacy: second\n",
            "      Project:\n        a: first\n      Project:\n        b: second\n",
        ):
            with self.subTest(replacements=replacements):
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as file:
                    file.write(
                        "service_connections:\n  policy:\n    replacements:\n" + replacements
                    )
                    file.flush()
                    with self.assertRaisesRegex(ValueError, "Duplicate"):
                        MODULE.load_service_connection_policies(file.name)

    @mock.patch.dict(MODULE.os.environ, {"SYSTEM_TEAMPROJECT": "Project name"})
    @mock.patch.object(MODULE, "notify_slack")
    @mock.patch.object(MODULE, "get_endpoint_identity_info")
    @mock.patch.object(MODULE, "get_service_endpoint")
    @mock.patch.object(MODULE, "get_current_identity_info")
    @mock.patch.object(MODULE, "load_service_connection_policies")
    def test_main_resolves_alias_once_and_uses_it_for_lookup_and_notice(
        self, load, current, endpoint, replacement, notify
    ):
        load.return_value = [("policy", self.config)]
        current.return_value = self.identity_info
        endpoint.return_value = self.replacement_endpoint
        replacement.return_value = self.replacement_identity_info
        with mock.patch.object(MODULE, "log_pipeline_issue") as issue:
            MODULE.main(
                ["--filepath", "map.yaml", "--service-connection", "legacy-connection"]
            )
        self.assertEqual(endpoint.call_args.args[0], "renamed-connection-WIF")
        self.assertIn("renamed-connection-WIF", issue.call_args.args[1])
        self.assertIn("renamed-connection-WIF", notify.call_args.args[2])

    @mock.patch.dict(MODULE.os.environ, {"SYSTEM_TEAMPROJECT": "Project name"})
    @mock.patch.object(MODULE, "notify_slack")
    @mock.patch.object(MODULE, "get_service_endpoint")
    @mock.patch.object(MODULE, "get_current_identity_info")
    @mock.patch.object(MODULE, "load_service_connection_policies")
    def test_main_unmapped_connection_skips_lookup_and_notifications(
        self, load, current, endpoint, notify
    ):
        load.return_value = [("policy", self.config)]
        current.return_value = self.identity_info
        self.assertEqual(
            MODULE.main(["--filepath", "map.yaml", "--service-connection", "unmapped"]),
            0,
        )
        endpoint.assert_not_called()
        notify.assert_not_called()

    @mock.patch.object(MODULE, "notify_slack")
    @mock.patch.object(MODULE, "get_service_endpoint")
    @mock.patch.object(MODULE, "get_current_identity_info")
    @mock.patch.object(MODULE, "load_service_connection_policies")
    def test_main_recognizes_valid_replacement_without_lookup_or_notifications(
        self, load, current, endpoint, notify
    ):
        load.return_value = [("policy", self.config)]
        current.return_value = self.replacement_identity_info
        with mock.patch.dict(MODULE.os.environ, {"SYSTEM_TEAMPROJECT": "PROJECT NAME"}):
            with self.assertLogs(MODULE.logger, level="INFO") as logs:
                result = MODULE.main(
                    [
                        "--filepath", "map.yaml",
                        "--service-connection", "RENAMED-CONNECTION-wif",
                    ]
                )
        self.assertEqual(result, 0)
        self.assertIn("no further action required", "\n".join(logs.output))
        self.assertNotIn("no policy matches", "\n".join(logs.output))
        endpoint.assert_not_called()
        notify.assert_not_called()

    @mock.patch.object(MODULE, "get_current_identity_info")
    @mock.patch.object(MODULE, "load_service_connection_policies")
    def test_main_does_not_claim_unverified_connections_are_correct(self, load, current):
        load.return_value = [("policy", self.config)]
        for project, connection, identity in (
            ("Other project", "renamed-connection-WIF", self.replacement_identity_info),
            ("Project name", "unknown-WIF", self.replacement_identity_info),
            ("", "renamed-connection-WIF", self.replacement_identity_info),
            (
                "Project name", "renamed-connection-WIF",
                {"identity_type": "ManagedIdentity", "identity_name": "unexpected"},
            ),
            (
                "Project name", "renamed-connection-WIF",
                {"identity_type": "Unknown", "identity_name": "legacy-WIF-mi"},
            ),
        ):
            with self.subTest(project=project, connection=connection, identity=identity):
                current.return_value = identity
                with mock.patch.dict(MODULE.os.environ, {"SYSTEM_TEAMPROJECT": project}):
                    with self.assertLogs(MODULE.logger, level="INFO") as logs:
                        result = MODULE.main(
                            [
                                "--filepath", "map.yaml",
                                "--service-connection", connection,
                            ]
                        )
                self.assertEqual(result, 0)
                self.assertIn("no policy matches", "\n".join(logs.output))
                self.assertNotIn("no further action required", "\n".join(logs.output))

    def test_policy_selection_ignores_policy_identifier(self):
        policies = [("arbitrary-policy-id", self.config)]

        result = MODULE.select_service_connection_policy(
            policies, "ServicePrincipal"
        )

        self.assertEqual(result, ("arbitrary-policy-id", self.config))

    def test_policy_selection_returns_none_when_identity_type_does_not_match(self):
        policies = [("arbitrary-policy-id", self.config)]

        result = MODULE.select_service_connection_policy(
            policies, "ManagedIdentity"
        )

        self.assertIsNone(result)

    def test_policy_selection_fails_if_identity_type_is_ambiguous(self):
        policies = [
            ("first-policy", self.config),
            ("second-policy", self.config),
        ]

        with self.assertRaisesRegex(ValueError, "Multiple service connection policies"):
            MODULE.select_service_connection_policy(policies, "ServicePrincipal")

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
        query = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(query["actionFilter"], ["view"])
        self.assertNotIn("endpointNames", query)
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
            replacement_name="renamed-connection-WIF",
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
            replacement_name="renamed-connection-WIF",
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
            replacement_name="renamed-connection-WIF",
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
            replacement_name="renamed-connection-WIF",
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
            replacement_name="renamed-connection-WIF",
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
            replacement_name="renamed-connection-WIF",
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
            replacement_name="renamed-connection-WIF",
        )

        self.assertEqual(result, 1)
        self.assertEqual(log_issue.call_args.args[0], "error")
        self.assertIn("renamed-connection-WIF", log_issue.call_args.args[1])
        notify.assert_called_once()
        self.assertIn("renamed-connection-WIF", notify.call_args.args[2])

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
