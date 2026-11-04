#!/usr/bin/env python3

import argparse
import datetime
import json
import logging
import os
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


logger = logging.getLogger("ado-service-connection-nagger")


class UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        keys = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ValueError("Deprecation map keys must be strings")
            if key in keys:
                raise ValueError(f"Duplicate deprecation map key: '{key}'")
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


def validate_replacements(replacements, policy_id):
    if not isinstance(replacements, dict):
        raise ValueError(f"Policy '{policy_id}' replacements must be a mapping")
    projects = set()
    for project, connections in replacements.items():
        if not isinstance(project, str) or not project.strip():
            raise ValueError(f"Policy '{policy_id}' has an invalid replacement project")
        if project.casefold() in projects:
            raise ValueError(f"Duplicate replacement project: '{project}'")
        projects.add(project.casefold())
        if not isinstance(connections, dict):
            raise ValueError(f"Replacements for project '{project}' must be a mapping")
        names = set()
        for name, replacement in connections.items():
            if not all(
                isinstance(value, str) and value.strip()
                for value in (name, replacement)
            ):
                raise ValueError(f"Project '{project}' has an invalid replacement name")
            if name.casefold() in names:
                raise ValueError(f"Duplicate replacement connection in '{project}': '{name}'")
            names.add(name.casefold())


def resolve_replacement_name(config, project, service_connection):
    if not project or not project.strip():
        raise RuntimeError(
            "SYSTEM_TEAMPROJECT is required to resolve service connection replacements"
        )
    for project_name, connections in config["replacements"].items():
        if project_name.casefold() == project.casefold():
            for name, replacement in connections.items():
                if name.casefold() == service_connection.casefold():
                    return replacement
            break
    logger.info(
        "Skipping deprecation notice for '%s' in project '%s': no replacement mapping exists",
        service_connection,
        project,
    )
    return None


def load_service_connection_policies(filepath):
    with open(filepath, encoding="utf-8") as config_file:
        config = yaml.load(config_file, Loader=UniqueKeyLoader) or {}

    connections = config.get("service_connections", {})
    if not isinstance(connections, dict):
        raise ValueError("'service_connections' must be a mapping")

    policies = []
    for policy_id, connection in connections.items():
        if not isinstance(connection, dict):
            raise ValueError(
                f"Service connection policy '{policy_id}' must be a mapping"
            )

        identity_type = connection.get("identity_type")
        replacements = connection.get("replacements")
        deadline = connection.get("date_deadline")
        required = {
            "identity_type": identity_type,
            "date_deadline": deadline,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(
                f"Service connection policy '{policy_id}' is missing required "
                f"configuration: {', '.join(missing)}"
            )
        validate_replacements(replacements, policy_id)

        if isinstance(deadline, datetime.datetime):
            deadline = deadline.date()
        elif not isinstance(deadline, datetime.date):
            deadline = datetime.date.fromisoformat(str(deadline))
        policies.append(
            (
                policy_id,
                {
                    **connection,
                    "identity_type": identity_type,
                    "replacements": replacements,
                    "date_deadline": deadline,
                },
            )
        )
    return policies


def select_service_connection_policy(policies, identity_type):
    matching_policies = [
        (policy_id, policy)
        for policy_id, policy in policies
        if policy["identity_type"] == identity_type
    ]
    if len(matching_policies) > 1:
        policy_ids = ", ".join(policy_id for policy_id, _ in matching_policies)
        raise ValueError(
            f"Multiple service connection policies match identity type "
            f"'{identity_type}': {policy_ids}"
        )
    return matching_policies[0] if matching_policies else None


def normalize_identity_type(service_principal_type):
    if service_principal_type == "Application":
        return "ServicePrincipal"
    return service_principal_type


def get_service_principal_info(client_id):
    try:
        result = subprocess.run(
            [
                "az",
                "ad",
                "sp",
                "show",
                "--id",
                client_id,
                "--query",
                "{identity_type:servicePrincipalType,identity_name:displayName}",
                "--output",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        message = (
            f"Could not inspect service principal '{client_id}': "
            f"az ad sp show exited with status {error.returncode}"
        )
        stderr = (error.stderr or "").strip()
        if stderr:
            message += f": {stderr}"
        raise RuntimeError(message) from error
    info = json.loads(result.stdout)
    if not isinstance(info, dict) or not info.get("identity_type") or not info.get("identity_name"):
        raise RuntimeError(
            f"Azure returned incomplete identity details for service principal '{client_id}'"
        )
    return {
        "identity_type": normalize_identity_type(info["identity_type"]),
        "identity_name": info["identity_name"],
    }


def get_current_identity_info():
    account_result = subprocess.run(
        ["az", "account", "show", "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    account = json.loads(account_result.stdout)
    user = account.get("user", {})
    client_id = user.get("name")
    if user.get("type") != "servicePrincipal" or not client_id:
        raise RuntimeError(
            "Azure CLI is not authenticated as a service principal for the "
            "configured service connection"
        )
    return get_service_principal_info(client_id)


def log_pipeline_issue(issue_type, message):
    print(f"##vso[task.logissue type={issue_type}]{message}")


def notify_slack(webhook_url, github_user, message):
    if not webhook_url:
        log_pipeline_issue(
            "warning",
            "Missing slack webhook URL. Please report via #platops-help on Slack.",
        )
        return
    if not github_user:
        log_pipeline_issue(
            "warning",
            "Cannot send Slack report because the build's GitHub author is unavailable.",
        )
        return

    slack_user_id = get_github_slack_user_mapping(
        get_hmcts_github_slack_user_mappings(), github_user
    )
    if not slack_user_id:
        log_pipeline_issue(
            "warning",
            "Cannot send Slack report: the GitHub author does not have an entry in "
            "https://github.com/hmcts/github-slack-user-mappings. "
            "Please add an entry and rerun the pipeline.",
        )
        return
    if slack_user_id == "iamabotuser":
        logger.info("Skipping Slack report for bot author '%s'", github_user)
        return

    send_slack_message(webhook_url, slack_user_id, message)


def get_hmcts_github_slack_user_mappings():
    request = Request(
        "https://raw.githubusercontent.com/"
        "hmcts/github-slack-user-mappings/master/slack.json"
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError) as error:
        raise RuntimeError(f"Could not retrieve GitHub-to-Slack mappings: {error}") from error


def get_github_slack_user_mapping(mappings, github_id):
    for user in mappings.get("users", []):
        if user.get("github") == github_id:
            return user.get("slack")
    return None


def send_slack_message(webhook_url, recipient, message):
    payload = json.dumps(
        {
            "channel": recipient,
            "username": "PlatOps Service Connection Nagger",
            "icon_emoji": ":warning:",
            "text": message,
        }
    ).encode("utf-8")
    request = Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            response_body = response.read().decode("utf-8")
            if response.status < 200 or response.status >= 300 or response_body != "ok":
                raise RuntimeError(
                    f"Slack webhook returned HTTP {response.status}: {response_body}"
                )
    except (HTTPError, URLError) as error:
        raise RuntimeError(f"Could not send Slack deprecation warning: {error}") from error


def check_service_connection(
    service_connection,
    config,
    identity_info,
    today,
    slack_webhook_url,
    build_repository,
    build_url,
    github_user,
    slack_notifications_enabled=True,
    *,
    replacement_name,
):
    if identity_info["identity_type"] != config["identity_type"]:
        logger.info(
            "Skipping deprecation notice for '%s': identity type is '%s', expected '%s'",
            service_connection,
            identity_info["identity_type"],
            config["identity_type"],
        )
        return 0

    deadline = config["date_deadline"]
    after_deadline = today > deadline
    level = "error" if after_deadline else "warning"
    status = "is deprecated and must be replaced" if after_deadline else "is deprecated"
    documentation_link = "https://hmcts.atlassian.net/wiki/spaces/DTSPO/pages/362971462/DTSPO-34618+-+Service+principal+connections+and+their+WIF+replacements"
    message = (
        f"Service connection '{service_connection}' {status}. "
        f"\nPlease replace existing service connection in your pipeline with '{replacement_name}' before deprecation deadline {deadline.isoformat()}. "
        f"\nFor more information, see the service connection migration guidance - {documentation_link}. "
    )
    log_pipeline_issue(level, message)

    slack_message = (
        f"{message}\nRepository: {build_repository or 'unknown'}"
        f"\nPipeline: {build_url or 'unknown'}"
    )
    if slack_notifications_enabled:
        notify_slack(slack_webhook_url, github_user, slack_message)
    else:
        logger.info("Slack notification disabled by configuration")
    return 1 if after_deadline else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="ADO service connection deprecation nagger")
    parser.add_argument("--filepath", required=True, help="Path to the deprecation map YAML")
    parser.add_argument("--service-connection", required=True, help="ADO service connection name")
    parser.add_argument(
        "--slack-notifications",
        choices=("true", "false"),
        default="true",
        help="Enable or disable Slack notifications (default: enabled)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        handlers=[logging.StreamHandler(stream=sys.stdout)],
    )

    policies = load_service_connection_policies(args.filepath)
    if not policies:
        logger.info("No service connection deprecation policies are configured")
        return 0

    current_identity_info = get_current_identity_info()
    logger.info(
        "Using service connection '%s' with identity '%s' (type: %s)",
        args.service_connection,
        current_identity_info["identity_name"],
        current_identity_info["identity_type"],
    )
    selected_policy = select_service_connection_policy(
        policies, current_identity_info["identity_type"]
    )
    if selected_policy is None:
        project = os.getenv("SYSTEM_TEAMPROJECT", "")
        already_using_replacement = any(
            current_identity_info["identity_type"] == "ManagedIdentity"
            and any(
                project_name.casefold() == project.casefold()
                and any(
                    name.casefold() == args.service_connection.casefold()
                    for name in connections.values()
                )
                for project_name, connections in policy["replacements"].items()
            )
            for _, policy in policies
        )
        if already_using_replacement:
            logger.info(
                "Correct service connection '%s' is already in use; "
                "no further action required",
                args.service_connection,
            )
            return 0
        logger.info(
            "Skipping service connection '%s': no policy matches identity type '%s'",
            args.service_connection,
            current_identity_info["identity_type"],
        )
        return 0
    policy_id, config = selected_policy
    logger.info(
        "Selected deprecation policy '%s' for service connection '%s'",
        policy_id,
        args.service_connection,
    )

    replacement_name = resolve_replacement_name(
        config, os.getenv("SYSTEM_TEAMPROJECT"), args.service_connection
    )
    if replacement_name is None:
        return 0

    logger.info("Using replacement '%s' from the deprecation map", replacement_name)
    return check_service_connection(
        service_connection=args.service_connection,
        replacement_name=replacement_name,
        config=config,
        identity_info=current_identity_info,
        today=datetime.date.today(),
        slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
        build_repository=os.getenv("BUILD_REPOSITORY_NAME"),
        build_url=f'{os.getenv("SYSTEM_COLLECTIONURI")}{os.getenv("SYSTEM_TEAMPROJECT")}/_build/results?buildId={os.getenv("BUILD_BUILDID")}',
        github_user=os.getenv("BUILD_SOURCEVERSIONAUTHOR"),
        slack_notifications_enabled=args.slack_notifications == "true",
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        yaml.YAMLError,
    ) as error:
        log_pipeline_issue("error", str(error))
        logger.error("%s", error)
        sys.exit(1)
