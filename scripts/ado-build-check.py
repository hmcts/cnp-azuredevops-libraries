import re
import sys
import json
import time
import argparse
import logging
import requests
from requests.auth import HTTPBasicAuth

retry_time_in_seconds = 10

parser = argparse.ArgumentParser(description="Prevent parallel ADO Pipeline run")

parser.add_argument("--pat", type=str, help="Specify the ADO PAT token")
parser.add_argument(
    "--organization",
    type=str,
    help="Specify ADO Organisation",
    required=True,
)
parser.add_argument(
    "--project",
    type=str,
    help="Specify ADO Project",
    required=True,
)
parser.add_argument(
    "--pipelineid",
    type=str,
    help="Specify ADO pipeline id",
    required=True,
)
parser.add_argument(
    "--buildid", type=int, help="Current ADO run build id", required=True
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
args = parser.parse_args()

logging.basicConfig(
    level=args.loglevel,
    format="[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(stream=sys.stdout),
    ],
)
logger = logging.getLogger()

organization = args.organization
project = args.project
pat = args.pat
buildid = args.buildid
pipelineid = args.pipelineid

ado_definition_url = (
    "https://dev.azure.com/"
    + f"{organization}/"
    + f"{project}"
    + "/_apis/build/builds?api-version=5.1&definitions="
    + f"{pipelineid}"
)
logger.info(f'ADO Pipeline definition URL is : "{ado_definition_url}"')
logger.info(f"Provided build id is : {buildid}")


def get_builds(buildid, ado_definition_url):
    """
    This function takes a build ID and an ADO Definition URL and returns a list of builds
    with information about their ID, build number, status, queue time, URL, and requested by.

    Parameters:
    buildid (int): The ID of the build for which to return other builds.
    ado_definition_url (str): The URL of the ADO definition.

    Returns:
    list: A list of builds with information about their ID, build number,
    status, queue time, URL, and requested by.

    Raises:
    Exception: If an exception is raised, the debug info of the builds is logged.

    This function will make a GET request to the provided ADO Definition URL, using an
    authentication token (PAT) if provided. If the request is successful, it will parse
    the returned JSON data to find builds with in progress status, and return a list
    containing information about each of those builds. If the build ID provided is not
    found in the returned builds, the function will log an error. If the request is not
    successful, the function will log an error containing the relevant debug info.
    In case of any exceptions, the function will raise an exception with the relevant
    debug info.
    """
    try:
        builds = requests.get(ado_definition_url, auth=HTTPBasicAuth("user", pat))
        if builds:
            builds = builds.json()
            if "value" in builds:
                builds = builds["value"]
                build_ids = [build["id"] for build in builds]
                if buildid not in build_ids:
                    logger.error(f"Provided build id {buildid} not found in builds.")
                    return False

                build_ids_in_progress = [
                    build["id"] for build in builds if "inProgress" in build["status"]
                ]
                if min(build_ids_in_progress) == buildid:
                    logger.info(f"Build id {buildid} is next in queue. Exiting...")
                    return

                return [
                    {
                        "id": build["id"],
                        "buildNumber": build["buildNumber"],
                        "status": build["status"],
                        "queueTime": build["queueTime"],
                        "url": build["url"],
                        "requestedBy": build["requestedBy"],
                    }
                    for build in builds
                    if "inProgress" in build["status"] and build["id"] != buildid
                ]
        if builds.status_code == 401 and len(builds.text) == 0:
            logger.error("401 response - PAT token provided is invalid")
            raise SystemExit(1)
        if not builds:
            try:
                if "<title>" in builds.text:
                    # Try to parse title HTML tag if HTML error type.
                    title = re.findall("<title>(.*?)</title>", builds.text)
                    if title:
                        logger.error(title)
                        raise SystemExit(1)
                    else:
                        logger.error(builds.text)
                        raise SystemExit(1)
                else:
                    logger.error(builds.content)
                    raise SystemExit(1)
            except Exception as e:
                logger.info("Unknown error...\n\n")
                raise Exception(e)

    except Exception as e:
        raise Exception(e)


def main():
    """
    The main() function is responsible for looping through the list of builds that are in progress and displaying their information.
    If there are no builds in progress, it will exit the loop and terminate. If there are builds in progress, it will log the information
    of each build and wait a specified time before checking again.

    Args:
      builds_in_progress (list): A list of builds that are currently in progress.
      retry_time_in_seconds (int): The time in seconds to wait before checking again.
      buildid (int): The ID of the build.
      ado_definition_url (str): The URL of the Azure DevOps definition.

    Returns:
      None
    """

    while True:
        builds_in_progress = get_builds(buildid, ado_definition_url)
        if isinstance(builds_in_progress, list):
            if len(builds_in_progress) > 0:
                logger.info(
                    f"There is currently {len(builds_in_progress)} builds in progress..."
                )
                logger.info(json.dumps(builds_in_progress, indent=4))
                logger.info(f"Re-trying in {retry_time_in_seconds} seconds...")
                time.sleep(retry_time_in_seconds)
            else:
                logger.info("There are no other builds in progress...")
                break
        else:
            break


if __name__ == "__main__":
    main()
