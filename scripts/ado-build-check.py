import argparse
import json
import logging
import re
import sys
import time
from typing import Any

import requests

RETRY_TIME_IN_SECONDS = 10
DEFAULT_MAX_WAIT_SECONDS = 800

logger = logging.getLogger(__name__)

# Runtime settings are assigned in main().
organization = ""
project = ""
pat = ""
buildid = 0
pipelineid = ""
include_release_branches = False
max_wait_seconds = DEFAULT_MAX_WAIT_SECONDS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prevent parallel ADO pipeline run")
    parser.add_argument("--pat", type=str, help="Specify the ADO PAT token")
    parser.add_argument(
        "--organization",
        type=str,
        help="Specify ADO organization",
        required=True,
    )
    parser.add_argument(
        "--project",
        type=str,
        help="Specify ADO project",
        required=True,
    )
    parser.add_argument(
        "--pipelineid",
        type=str,
        help="Specify ADO pipeline id",
        required=True,
    )
    parser.add_argument("--buildid", type=int, help="Current ADO run build id", required=True)
    parser.add_argument(
        "--include-release-branches",
        help="Treat refs/heads/release/* as mainline priority branches",
        action="store_true",
    )
    parser.add_argument(
        "--max-wait-seconds",
        type=int,
        default=DEFAULT_MAX_WAIT_SECONDS,
        help="Maximum seconds to wait before failing the concurrency gate",
    )
    parser.add_argument(
        "-d",
        "--debug",
        help="Show debug logs",
        action="store_const",
        dest="loglevel",
        const=logging.DEBUG,
        default=logging.INFO,
    )
    return parser.parse_args(argv)


def configure_logging(loglevel: int) -> None:
    logging.basicConfig(
        level=loglevel,
        format="[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s: %(message)s",
        handlers=[logging.StreamHandler(stream=sys.stdout)],
    )


def get_ado_definition_url(org: str, team_project: str, definition_id: str) -> str:
    return (
        "https://dev.azure.com/"
        + f"{org}/"
        + f"{team_project}"
        + "/_apis/build/builds?api-version=7.1&definitions="
        + f"{definition_id}"
    )


def get_request_headers() -> dict[str, str]:
    return {"Authorization": "Bearer " + pat, "Content-Type": "application/json"}


def is_mainline_branch(source_branch: str) -> bool:
    if source_branch in {"refs/heads/main", "refs/heads/master"}:
        return True
    if include_release_branches and source_branch.startswith("refs/heads/release/"):
        return True
    return False


def is_pr_build(build: dict[str, Any]) -> bool:
    reason = (build.get("reason") or "").lower()
    source_branch = build.get("sourceBranch") or ""
    return reason == "pullrequest" or source_branch.startswith("refs/pull/")


def is_manual_build(build: dict[str, Any]) -> bool:
    reason = (build.get("reason") or "").lower()
    return reason == "manual"


def classify_build(build: dict[str, Any]) -> str:
    source_branch = build.get("sourceBranch") or ""
    if is_mainline_branch(source_branch):
        return "mainline"
    if is_manual_build(build):
        return "manual"
    if is_pr_build(build):
        return "pr"
    return "other"


def class_priority(build_class: str) -> int:
    priorities = {
        "mainline": 0,
        "manual": 1,
        "pr": 2,
        "other": 3,
    }
    return priorities.get(build_class, 3)


def build_summary(build: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": build.get("id"),
        "buildNumber": build.get("buildNumber"),
        "status": build.get("status"),
        "queueTime": build.get("queueTime"),
        "startTime": build.get("startTime"),
        "sourceBranch": build.get("sourceBranch"),
        "reason": build.get("reason"),
        "url": build.get("url"),
        "requestedBy": build.get("requestedBy"),
        "class": classify_build(build),
    }


def select_competing_builds(
    current_build: dict[str, Any],
    in_progress_builds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return builds that are allowed to block current build under priority policy."""
    current_class = classify_build(current_build)
    current_priority = class_priority(current_class)
    competitors = [current_build]

    for other_build in in_progress_builds:
        other_class = classify_build(other_build)
        other_priority = class_priority(other_class)

        # Higher-priority or same-priority classes can block; lower-priority classes cannot.
        if other_priority <= current_priority:
            competitors.append(other_build)

    return competitors


def competitor_log_details(builds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": build.get("id"),
            "class": classify_build(build),
            "reason": build.get("reason"),
            "sourceBranch": build.get("sourceBranch"),
        }
        for build in builds
    ]


def get_builds(current_build_id: int, ado_definition_url: str) -> list[dict[str, Any]] | None:
    """Return competing in-progress builds for current build, or None if current build may proceed."""
    try:
        response = requests.get(
            ado_definition_url,
            headers=get_request_headers(),
            timeout=30,
        )
        if response.status_code == 401 and len(response.text) == 0:
            logger.error("401 response - token provided is invalid")
            raise SystemExit(1)

        response.raise_for_status()
    except requests.RequestException as error:
        logger.error("ADO builds query failed: %s", error)
        raise

    try:
        payload = response.json()
    except ValueError as error:
        logger.error("ADO builds query returned invalid JSON")
        raise RuntimeError("Invalid JSON payload from ADO builds API") from error

    logger.debug("Provided builds.json is : %s", payload)
    builds = payload.get("value", [])
    if not builds:
        raise RuntimeError("No build data returned for pipeline definition")

    build_ids = [build.get("id") for build in builds]
    if current_build_id not in build_ids:
        raise RuntimeError(f"Provided build id {current_build_id} not found in builds")

    in_progress_builds = [
        build for build in builds if "inProgress" in (build.get("status") or "")
    ]
    current_build = next(
        (build for build in in_progress_builds if build.get("id") == current_build_id),
        None,
    )
    if not current_build:
        logger.info("Current build %s is not in progress anymore. Exiting...", current_build_id)
        return None

    other_in_progress = [
        build for build in in_progress_builds if build.get("id") != current_build_id
    ]

    competitors = select_competing_builds(current_build, other_in_progress)
    logger.info(
        "Build id %s classified as %s. Total in-progress seen=%s. Policy competitors=%s",
        current_build_id,
        classify_build(current_build),
        len(in_progress_builds),
        competitor_log_details([build for build in competitors if build.get("id") != current_build_id]),
    )

    if min(build["id"] for build in competitors) == current_build_id:
        logger.info(
            "Build id %s can proceed under policy (class=%s).",
            current_build_id,
            classify_build(current_build),
        )
        return None

    return [
        build_summary(build)
        for build in competitors
        if build.get("id") != current_build_id
    ]


def main(argv: list[str] | None = None) -> int:
    global organization
    global project
    global pat
    global buildid
    global pipelineid
    global include_release_branches
    global max_wait_seconds

    args = parse_args(argv)
    configure_logging(args.loglevel)

    organization = args.organization
    project = args.project
    pat = args.pat
    buildid = args.buildid
    pipelineid = args.pipelineid
    include_release_branches = args.include_release_branches
    max_wait_seconds = max(1, args.max_wait_seconds)

    ado_definition_url = get_ado_definition_url(organization, project, pipelineid)
    wait_start = time.monotonic()

    while True:
        elapsed = int(time.monotonic() - wait_start)
        if elapsed > max_wait_seconds:
            logger.warning(
                "Timed out waiting for concurrency gate after %s seconds (max %s). Proceeding without further blocking.",
                elapsed,
                max_wait_seconds,
            )
            return 0

        builds_in_progress = get_builds(buildid, ado_definition_url)
        if isinstance(builds_in_progress, list) and builds_in_progress:
            logger.info(
                "There are currently %s competing builds in progress...",
                len(builds_in_progress),
            )
            logger.info(json.dumps(builds_in_progress, indent=4))
            logger.info("Re-trying in %s seconds...", RETRY_TIME_IN_SECONDS)
            time.sleep(RETRY_TIME_IN_SECONDS)
            continue

        logger.info("There are no competing builds in progress...")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
