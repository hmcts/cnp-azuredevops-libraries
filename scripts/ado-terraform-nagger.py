import os
import re
import sys
import json
import logging
import argparse
import subprocess
from packaging import version
from json.decoder import JSONDecodeError

config = {
    "terraform": {"warn_below": "1.3.7", "error_below": "0.12.0"},
    "providers": {
        "registry.terraform.io/chilicat/pkcs12": {
            "warn_below": "0.0.7",
            "error_below": "0.0.5",
        },
        "registry.terraform.io/dynatrace-oss/dynatrace": {
            "warn_below": "1.18.1",
            "error_below": "1.16.0",
        },
        "registry.terraform.io/hashicorp/azuread": {
            "warn_below": "2.33.0",
            "error_below": "2.19.1",
        },
        "registry.terraform.io/hashicorp/azurerm": {
            "warn_below": "3.42.0",
            "error_below": "2.99.0",
        },
        "registry.terraform.io/integrations/github": {
            "warn_below": "5.16.0",
            "error_below": "5.3.0",
        },
        "registry.terraform.io/microsoft/azuredevops": {
            "warn_below": "0.3.0",
            "error_below": "0.1.0",
        },
        "registry.terraform.io/paloaltonetworks/panos": {
            "warn_below": "1.11.0",
            "error_below": "1.10.0",
        },
    },
}

parser = argparse.ArgumentParser(description="ADO Terraform version nagger")
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

semver_regex = (
    "\\s*(?:v\\.?)?(?P<major>\\d+)\\. (?P<minor>\\d+)\\. (?P<patch>\\d+)"
    "(?:-(?P<pre>(?:[0-9A-Za-z-]|[1-9A-Za-z-][0-9A-Za-z-]*)"
    "(?:\\.[0-9A-Za-z-]|[1-9A-Za-z-][0-9A-Za-z-]*)*))?"
    "(?:\\+(?P<meta>[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*))?\\s*$"
)


def log_message(message):
    """
    This function logs a given message with the logging library and,
    if the system is running in Azure DevOps
    (as determined by the presence of the SYSTEM_ACCESSTOKEN environment variable),
    it also logs a warning issue with Azure DevOps.

    Args:
    message (str): The message to be logged.

    Returns:
    None
    """
    logger.warning(message)
    is_ado = os.getenv("SYSTEM_ACCESSTOKEN")
    if is_ado:
        logger.warning(f"##vso[task.logissue type=warning;]{message}")


def extract_version(text, regex):
    """
    This function searches for a version number in the input `text`
    using the specified regular expression `regex`.
    If a match is found, the version number is returned as a string.
    If no match is found, the function returns None.

    Parameters:
        text (str): The input text to be searched.
        regex (str): The regular expression pattern used to search for the version.
                     (regex must include "semver" named match group)

    Returns:
        str: The version number as a string if found, otherwise None.
    """
    matches = re.finditer(regex, text, re.MULTILINE | re.IGNORECASE | re.VERBOSE)
    for match in matches:
        return match.group("semver").strip()
    else:
        return None


def terraform_version_checker(terraform_version):
    # Error if terraform version is lower than specified within config.
    if version.parse(terraform_version) < version.parse(
        config["terraform"]["error_below"]
    ):
        log_message(
            f"Detected terraform version {terraform_version} "
            f'is lower than {config["terraform"]["error_below"]}. '
            "Exiting..."
        )
        raise SystemExit(1)

    # Warn if terraform version is lower than specified within config.
    if version.parse(terraform_version) < version.parse(
        config["terraform"]["warn_below"]
    ):
        logger.warning(
            f"Detected terraform version {terraform_version} "
            f'is lower than {config["terraform"]["warn_below"]}. '
            "Please upgrade..."
        )


def main():

    command = ["terraform", "version", "--json"]

    try:
        # Try to run `version --json` which is present in tf versions >= 0.13.0
        run_command = subprocess.run(command, capture_output=True)
        result = json.loads(run_command.stdout.decode("utf-8"))
        terraform_version = result["terraform_version"]

        # Handle terraform versions
        terraform_version_checker(terraform_version)

        # Handle providers
        terraform_providers = result["provider_selections"]

        for provider in terraform_providers:
            if provider not in config["providers"]:
                log_message(
                    f"Provider {provider} is missing from version config. "
                    "Please add it to the config in this file in order to "
                    "compare it's versions."
                )
            else:
                # Handle providers
                # Error if provider version is lower than specified within config.
                if version.parse(terraform_providers[provider]) < version.parse(
                    config["providers"][provider]["error_below"]
                ):
                    log_message(
                        f"Detected provider {provider} version "
                        f"{terraform_providers[provider]} "
                        "is lower than "
                        f'{config["providers"][provider]["error_below"]}. '
                        "Exiting..."
                    )
                    raise SystemExit(1)

                # Warn if provider version is lower than specified within config.
                if version.parse(terraform_providers[provider]) < version.parse(
                    config["providers"][provider]["warn_below"]
                ):
                    log_message(
                        f"Detected provider {provider} version "
                        f"{terraform_providers[provider]} "
                        "is lower than "
                        f'{config["providers"][provider]["warn_below"]}. '
                        "Please upgrade..."
                    )

    except JSONDecodeError:
        # Fallback to regex when terraform version <= 0.13.0
        run_command = subprocess.run(command, capture_output=True)
        result = run_command.stdout.decode("utf-8")
        terraform_regex = f"^([Tt]erraform(\\s))(?P<semver>{semver_regex})"
        terraform_version = extract_version(result, terraform_regex)
        log_message(
            f"Detected terraform version {terraform_version} does not support "
            "checking provider versions in addition to the main binary. "
            "Please upgrade youre terraform version to at least v0.13.0"
        )
        # Strip preceding "v" for version comparison.
        if terraform_version[0].lower() == "v":
            terraform_version = terraform_version[1:]

        # Handle terraform versions.
        terraform_version_checker(terraform_version)
    except Exception as e:
        logger.error("Unknown error occurred")
        raise Exception(e)


if __name__ == "__main__":
    main()
