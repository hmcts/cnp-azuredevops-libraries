import sys
import json
import time
import argparse
import logging
import requests
from requests.auth import HTTPBasicAuth


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(stream=sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

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

args = parser.parse_args()

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
logger.info(f"ADO Pipeline definition URL is : {ado_definition_url}")
logger.info(f"Current build id is : {buildid}")


def get_builds(buildid, ado_definition_url):
    """
    This function takes a build ID and an ADO Definition URL and returns a list of builds
    with information about their ID, build number, status, queue time, URL, and requested by.

    Parameters:
    buildid (int): The ID of the build for which to return other builds.
    ado_definition_url (str): The URL of the ADO definition.

    Returns:
    list: A list of builds with information about their ID, build number, status, queue time, URL, and requested by.

    Raises:
    Exception: If an exception is raised, the debug info of the builds is logged.
    """
    try:
        builds = requests.get(ado_definition_url, auth=HTTPBasicAuth("user", pat))
        builds = builds.json()["value"]

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
    except Exception as e:
        logger.info("Something went wrong... dislaying debug info below...")
        logger.info(builds.content)
        raise Exception(e)


def main():
    """
    This function checks if any builds are in progress, and if so, waits a
    specified amount of time before checking again.

    Requires parameters:
    buildid (str): The build ID
    ado_definition_url (str): The ADO definition URL

    Returns:
    None
    """
    while True:
        builds_in_progress = get_builds(buildid, ado_definition_url)
        if len(builds_in_progress) > 0:
            logger.info(
                f"There is currently {len(builds_in_progress)} builds in progress..."
            )
            logger.info(json.dumps(builds_in_progress, indent=4))
            logger.info("Checking again in 5 minutes...")
            time.sleep(10)
        else:
            logger.info("There are no other builds in progress...")
            logger.info("Carrying on...")
            break


if __name__ == "__main__":
    main()
