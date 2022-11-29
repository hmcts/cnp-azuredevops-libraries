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
        raise Exception(e)


def main():
    while True:
        builds_in_progress = get_builds(buildid, ado_definition_url)
        if len(builds_in_progress) > 0:
            logger.info(
                f"There is currently {len(builds_in_progress)} builds in progress..."
            )
            logger.info(json.dumps(builds_in_progress, indent=4))
            logger.info("Checking again in 5 minutes...")
            time.sleep(5)
        else:
            logger.info("There is no other builds in progress...")
            logger.info("Carrying on...")
            break


if __name__ == "__main__":
    main()
