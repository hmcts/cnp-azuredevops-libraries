#!/usr/bin/env python3

import argparse
import datetime
import json
import logging
import os
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import yaml


logger = logging.getLogger("ado-service-connection-nagger")


def load_service_connection_config(filepath, service_connection):
    with open(filepath, encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}

    connections = config.get("service_connections", {})
    if not isinstance(connections, dict):
        raise ValueError("'service_connections' must be a mapping")

    connection = connections.get(service_connection)
    if connection is None:
        return None
    if not isinstance(connection, dict):
        raise ValueError(
            f"Configuration for service connection '{service_connection}' must be a mapping"
        )

    identity_type = connection.get("identity_type")
    replacement_identity_type = connection.get("replacement_identity_type")
    replacement_identity_name_suffix = connection.get(
        "replacement_identity_name_suffix"
    )
    replacement_name_suffix = connection.get("replacement_name_suffix")
    deadline = connection.get("date_deadline")
    required = {
        "identity_type": identity_type,
        "replacement_identity_type": replacement_identity_type,
        "replacement_identity_name_suffix": replacement_identity_name_suffix,
        "replacement_name_suffix": replacement_name_suffix,
        "date_deadline": deadline,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise ValueError(
            f"Service connection '{service_connection}' is missing required "
            f"configuration: {', '.join(missing)}"
        )

    if isinstance(deadline, datetime.datetime):
        deadline = deadline.date()
    elif not isinstance(deadline, datetime.date):
        deadline = datetime.date.fromisoformat(str(deadline))
    return {
        **connection,
        "identity_type": identity_type,
        "replacement_identity_type": replacement_identity_type,
        "replacement_identity_name_suffix": replacement_identity_name_suffix,
        "replacement_name_suffix": replacement_name_suffix,
        "date_deadline": deadline,
    }


def normalize_identity_type(service_principal_type):
    if service_principal_type == "Application":
        return "ServicePrincipal"
    return service_principal_type


def get_service_principal_info(client_id):
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


def get_service_endpoint(service_connection, organization_url, project, access_token):
    if not organization_url or not project or not access_token:
        raise RuntimeError(
            "SYSTEM_COLLECTIONURI, SYSTEM_TEAMPROJECT, and SYSTEM_ACCESSTOKEN "
            "are required to inspect Azure DevOps service connections"
        )

    query = urlencode(
        {
            "endpointNames": service_connection,
            "api-version": "7.1",
        }
    )
    url = (
        f"{organization_url.rstrip('/')}/{quote(project, safe='')}"
        f"/_apis/serviceendpoint/endpoints?{query}"
    )
    request = Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError) as error:
        raise RuntimeError(
            f"Could not look up Azure DevOps service connection "
            f"'{service_connection}': {error}"
        ) from error

    endpoints = payload.get("value")
    if not isinstance(endpoints, list):
        raise RuntimeError("Azure DevOps returned an invalid service endpoint response")
    matches = [
        endpoint
        for endpoint in endpoints
        if endpoint.get("name", "").casefold() == service_connection.casefold()
    ]
    if len(matches) > 1:
        raise RuntimeError(
            f"More than one Azure DevOps service connection named "
            f"'{service_connection}' was returned"
        )
    return matches[0] if matches else None


def get_endpoint_identity_info(endpoint):
    try:
        client_id = endpoint["authorization"]["parameters"]["serviceprincipalid"]
    except (KeyError, TypeError) as error:
        raise RuntimeError(
            f"Azure DevOps service connection '{endpoint.get('name', 'unknown')}' "
            "does not expose a service principal ID"
        ) from error
    if not client_id:
        raise RuntimeError(
            f"Azure DevOps service connection '{endpoint.get('name', 'unknown')}' "
            "has an empty service principal ID"
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
    replacement_endpoint,
    replacement_identity_info,
    today,
    slack_webhook_url,
    build_repository,
    build_url,
    github_user,
    slack_notifications_enabled=True,
):
    if identity_info["identity_type"] != config["identity_type"]:
        logger.info(
            "Skipping deprecation notice for '%s': identity type is '%s', expected '%s'",
            service_connection,
            identity_info["identity_type"],
            config["identity_type"],
        )
        return 0

    replacement_name = service_connection + config["replacement_name_suffix"]
    if replacement_endpoint is None:
        logger.info(
            "Skipping deprecation notice for '%s': replacement service connection "
            "'%s' was not found",
            service_connection,
            replacement_name,
        )
        return 0

    if replacement_endpoint.get("name", "").casefold() != replacement_name.casefold():
        logger.info(
            "Skipping deprecation notice for '%s': found replacement service "
            "connection '%s', expected '%s'",
            service_connection,
            replacement_endpoint.get("name", "unknown"),
            replacement_name,
        )
        return 0

    if replacement_identity_info is None:
        raise RuntimeError(
            f"Replacement service connection '{replacement_name}' exists but its "
            "identity details were not retrieved"
        )

    if replacement_identity_info["identity_type"] != config["replacement_identity_type"]:
        logger.info(
            "Skipping deprecation notice for '%s': replacement identity type is '%s', "
            "expected '%s'",
            service_connection,
            replacement_identity_info["identity_type"],
            config["replacement_identity_type"],
        )
        return 0

    if not replacement_identity_info["identity_name"].endswith(
        config["replacement_identity_name_suffix"]
    ):
        logger.info(
            "Skipping deprecation notice for '%s': replacement identity name '%s' "
            "does not end with '%s'",
            service_connection,
            replacement_identity_info["identity_name"],
            config["replacement_identity_name_suffix"],
        )
        return 0

    deadline = config["date_deadline"]
    after_deadline = today > deadline
    level = "error" if after_deadline else "warning"
    status = "is deprecated and must be replaced" if after_deadline else "is deprecated"
    message = (
        f"Service connection '{service_connection}' {status}. "
        f"Use '{replacement_name}' by {deadline.isoformat()}. "
        f"See the service connection migration guidance."
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

    config = load_service_connection_config(args.filepath, args.service_connection)
    if config is None:
        logger.info("No deprecation-map entry for service connection '%s'", args.service_connection)
        return 0

    current_identity_info = get_current_identity_info()
    replacement_endpoint = None
    replacement_identity_info = None
    if current_identity_info["identity_type"] == config["identity_type"]:
        replacement_name = args.service_connection + config["replacement_name_suffix"]
        replacement_endpoint = get_service_endpoint(
            replacement_name,
            os.getenv("SYSTEM_COLLECTIONURI"),
            os.getenv("SYSTEM_TEAMPROJECT"),
            os.getenv("SYSTEM_ACCESSTOKEN"),
        )
        replacement_identity_info = (
            get_endpoint_identity_info(replacement_endpoint)
            if replacement_endpoint is not None
            else None
        )
    return check_service_connection(
        service_connection=args.service_connection,
        config=config,
        identity_info=current_identity_info,
        replacement_endpoint=replacement_endpoint,
        replacement_identity_info=replacement_identity_info,
        today=datetime.date.today(),
        slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
        build_repository=os.getenv("BUILD_REPOSITORY_NAME"),
        build_url=os.getenv("BUILD_BUILDURI"),
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
    ) as error:
        log_pipeline_issue("error", str(error))
        logger.error("%s", error)
        sys.exit(1)
