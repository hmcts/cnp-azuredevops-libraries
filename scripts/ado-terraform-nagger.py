import os
import re
import sys
import json
import logging
import argparse
import subprocess
from packaging import version
from json.decoder import JSONDecodeError

# Global variable used to exit with error at the end of all checks.
# To be updated from default value by logging function.
errors_detected = False

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

def load_file(filename):
    """
    This function loads a file from the same directory as the script itself.
    Args:
        filename (str): The name of the file to load.
    Returns:
        str: The contents of the file.
    Raises:
        FileNotFoundError: If the specified file does not exist.
    """
    # Get the path of the script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Construct the path to the file
    file_path = os.path.join(script_dir, filename)
    # Open and read the file
    try:
        with open(file_path, 'r') as f:
            contents = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"The file '{filename}' does not exist.")
    return contents

def log_message(message_type, message):
    """
    This function logs a given message with the logging library and,
    if the system is running in Azure DevOps
    (as determined by the SYSTEM_PIPELINESTARTTIME environment variable),
    it also logs a warning issue with Azure DevOps. If message_type is set to warning
    logger will log a warning type, if message_type is set to error logger will log an
    error type, ADO will also raise an error and stop task execution.

    Args:
    message_type(str): The message type, can be either warning or error.
    message (str): The message to be logged.

    Returns:
    None
    """
    global errors_detected

    logger.warning(message)
    is_ado = os.getenv("SYSTEM_PIPELINESTARTTIME")
    if is_ado:
        if message_type == "warning":
            logger.warning(f"##vso[task.logissue type=warning;]{message}")
        if message_type == "error":
            logger.error(f"##vso[task.logissue type=error;]{message}")
            errors_detected = True


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
    # Load config file with pre-defined versions
    try:
        filename = "ado-terraform-nagger-versions.json"
        config = json.loads(load_file(filename))
    except json.JSONDecodeError:
        logger.error(f"{filename} contains invalid JSON")
    except Exception as e:
        logger.error(f"Error loading {filename}: {e}")

    # Error if terraform version is lower than specified within config.
    if version.parse(terraform_version) < version.parse(
        config["terraform"]["error_below"]
    ):
        log_message(
            "error",
            f"Detected terraform version {terraform_version} "
            f'is lower than {config["terraform"]["error_below"]}. '
            "This is no longer allowed, please upgrade...",
        )

    # Warn if terraform version is lower than specified within config.
    if version.parse(terraform_version) < version.parse(
        config["terraform"]["warn_below"]
    ):
        log_message(
            "warning",
            f"Detected terraform version {terraform_version} "
            f'is lower than {config["terraform"]["warn_below"]}. '
            "Please upgrade...",
        )


def main():

    command = ["terraform", "version", "--json"]

    try:
        # Try to run `version --json` which is present in tf versions >= 0.13.0
        run_command = subprocess.run(command, capture_output=True)
        result = json.loads(run_command.stdout.decode("utf-8"))
        terraform_version = result["terraform_version"]

        # Use terraform's `terraform_outdated` JSON object to notify if there
        # is a new terraform version available.
        if "terraform_outdated" in result and result["terraform_outdated"]:
            log_message("warning", "Detected outdated terraform version.")

        # Handle terraform versions
        terraform_version_checker(terraform_version)

        # Handle providers
        terraform_providers = result["provider_selections"]

        for provider in terraform_providers:
            if provider not in config["providers"]:
                log_message(
                    "warning",
                    f"Provider {provider} is missing from version config. "
                    "Please add it to the config in this file in order to "
                    "compare it's versions.",
                )
            else:
                # Handle providers
                # Error if provider version is lower than specified within config.
                if version.parse(terraform_providers[provider]) < version.parse(
                    config["providers"][provider]["error_below"]
                ):
                    log_message(
                        "error",
                        f"Detected provider {provider} version "
                        f"{terraform_providers[provider]} "
                        "is lower than "
                        f'{config["providers"][provider]["error_below"]}. '
                        "This is no longer allowed, please upgrade...",
                    )

                # Warn if provider version is lower than specified within config.
                if version.parse(terraform_providers[provider]) < version.parse(
                    config["providers"][provider]["warn_below"]
                ):
                    log_message(
                        "warning",
                        f"Detected provider {provider} version "
                        f"{terraform_providers[provider]} "
                        "is lower than "
                        f'{config["providers"][provider]["warn_below"]}. '
                        "Please upgrade...",
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

    # Exit with error at the end of all checks so that we can see errors for all
    # unmet versions.
    if errors_detected:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
