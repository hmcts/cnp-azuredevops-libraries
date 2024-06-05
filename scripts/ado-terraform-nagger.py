#!/usr/bin/env python3

import os
import re
import sys
import datetime
import json
import yaml
import logging
import argparse
import requests
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
parser.add_argument(
    "-f",
    "--filepath",
    help="Filepath to nagger-versions.json",
    dest="filepath",
    required=True,
)
parser.add_argument(
    "-e",
    "--environment_components",
    help="JSON string of environment components",
    dest="environment_components",
    type=str,
    required=True,
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


def run_command(command, working_directory):
    """Run a command and return the output.
    Args:
        command (list): A list of command arguments.
    Returns:
        dict: The output of the command.
    Raises:
        subprocess.CalledProcessError: If the command returns a non-zero exit code.
        Exception: If any other error occurs.
    Note:
        This function will attempt to run the command using the `capture_output`
        parameter, which is only available in Python 3.7 or later. If this fails,
        it will fall back to using the `stdout` and `stderr` parameters instead.

    """
    os.chdir(working_directory)
    try:
        run_command = subprocess.run(command, capture_output=True)
        # debug with 2 lines
        output = run_command.stdout.decode("utf-8")
        print("Command output:", output)
        return run_command.stdout.decode("utf-8")
    except TypeError:
        run_command = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        # debug with 2 lines
        output = run_command.stdout.decode("utf-8")
        print("Command output:", output)
        return run_command.stdout.decode("utf-8")
    except subprocess.CalledProcessError as e:
        raise subprocess.CalledProcessError(e.returncode, e.cmd, e.output, e.stderr)
    except Exception as e:
        raise Exception(f"An error occurred: {e}")


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
        with open(file_path, "r") as f:
            contents = yaml.safe_load(f)
            return contents
    except FileNotFoundError:
        raise FileNotFoundError(f"The file '{filename}' does not exist.")
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error parsing YAML data: {e}")
    except Exception as e:
        logger.error(f"Error loading {filename}: {e}")


def send_slack_message(webhook, channel, username, icon_emoji, message, build_origin, build_url, build_id, components_str):
    """
    Sends a message to a Slack channel using a webhook.

    Args:
        webhook (str): The webhook URL for the Slack app.
        channel (str): The name or ID of the Slack channel to send the message to.
        username (str): The username to display as the sender of the message.
        message (str): The message text to send.
        icon_emoji (str): The emoji to use as the sender's icon, e.g. "smile" or "rocket".

    Returns:
        bool: True if the message was sent successfully.

    Raises:
        ValueError: If the Slack API returns an error.
    """
    slack_data = {
        "channel": channel,
        "username": username,
        "text": 'dummy_text',
        "icon_emoji": icon_emoji,
        "blocks": 
        [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Deprecated Config",
                    "emoji": True,
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": "*Source:*\n" + build_origin
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*Build:* " + build_id + "\n" + build_url
                    }
                ]
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": "*Warning:*\n" + message['warning']['error_message']
                    }
                ]
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": "*Components:*\n" + components_str
                    }
                ]
            }
        ]
    }

    response = requests.post(webhook, json=slack_data)
    if response.status_code:
        return True
    else:
        raise ValueError(
            f"Request to Slack returned an error: {response.status_code},"
            f"{response.text}"
        )


def get_hmcts_github_slack_user_mappings():
    """
    Retrieves a JSON file containing mappings between GitHub usernames and Slack user IDs.
    Returns:
        dict: A dictionary containing the mappings.
    Raises:
        requests.exceptions.RequestException: If an error occurs while making the request.
    """
    url = (
        "https://raw.githubusercontent.com/"
        "hmcts/github-slack-user-mappings/master/slack.json"
    )
    response = requests.get(url).json()
    return response


def get_github_slack_user_mapping(mappings, github_id):
    """
    Return the Slack ID of the user with the provided GitHub ID.
    If no user is found with the provided GitHub ID, return None.

    Parameters:
    - mappings (dict): A dictionary of user mappings containing 'users' key,
        which has a list of dictionaries where each dictionary has 'github'
        and 'slack' keys representing the GitHub ID and corresponding Slack
        ID respectively.
    - github_id (str): A string representing the GitHub ID of the user whose
        Slack ID is to be retrieved.

    Returns:
    - str or None: Returns a string representing the Slack ID of the user
        with the provided GitHub ID, or None if no user is found with the
        provided GitHub ID.
    """
    # Find the user with the provided GitHub ID and return their Slack ID
    for user in mappings["users"]:
        if user["github"] == github_id:
            return user["slack"]
    return None


def log_message_slack(slack_recipient=None, slack_webhook_url=None, message=None):
    """
    Sends a message to a Slack recipient using a webhook URL.

    If both `slack_recipient` and `slack_webhook_url` are provided, the function
    will send a message to the specified Slack channel or user using the
    provided webhook URL.

    Parameters:
    - message (str): A string representing the message to be sent to Slack.
    - slack_recipient (str): A string representing the name or ID of the Slack
        channel or user that the message will be sent to. If not provided, the
        message will not be sent.
    - slack_webhook_url (str): A string representing the webhook URL for the
        Slack integration that the message will be sent through. If not
        provided, the message will not be sent to Slack.

    Returns:
    - None
    """
    if slack_recipient and slack_webhook_url:
        # https://dev.azure.com/hmcts/PlatformOperations/_build/results?buildId=579391
        build_url = f'{os.getenv("SYSTEM_COLLECTIONURI")}{os.getenv("SYSTEM_TEAMPROJECT")}/_build/results?buildId={os.getenv("BUILD_BUILDID")}'
        repository = os.getenv("BUILD_REPOSITORY_URI")
        repository_name = repository.split("/")[-1]
        source_branch = os.getenv("BUILD_SOURCEBRANCH")
        source_branch_name = os.getenv("BUILD_SOURCEBRANCHNAME")
        build_id = os.getenv("BUILD_BUILDID")

        stage = os.getenv("SYSTEM_STAGEDISPLAYNAME")
        slack_sender = "cnp-azuredevops-libraries - terraform version nagger"

        # Differentiate PR from branch
        if source_branch.startswith("refs/pull"):
            # It's a pull request. Extract the pull request number       
            pull_request_number = source_branch.split("/")[2]
            build_origin_url = f"{repository}/pull/{pull_request_number}" # https://github.com/hmcts/cnp-dummy-library-test/pull/37
            build_origin = f"<{build_origin_url}|{repository_name}/pull/{pull_request_number}>"
        else:
            # It's a branch
            build_origin_url = f"{repository}/tree/{source_branch_name}" # https://github.com/hmcts/cnp-dummy-library-test/tree/dtspo-17345-reinstate-nagger
            build_origin = f"<{build_origin_url}|{repository_name}/tree/{source_branch_name}>"
        

        # Format message with useful information to quickly identify the stage,
        # component, repository and its branch.
        # build slack msg then send after
        slack_message = (
            f"\n"
            + f"We have noticed deprecated configuration in {build_origin}: <{build_url}|Build {build_id}>"
            + f"STAGE: {stage}\n"
            + f"MESSAGE: {message}\n"
        )
        icon_emoji = ":warning:"
        components_str = ', '.join(message['warning']['components'])

        send_slack_message(
            slack_webhook_url, slack_recipient, slack_sender, icon_emoji, message, build_origin, build_url, build_id, components_str
        )


def log_message(slack_recipient, slack_webhook_url, message_type, message):
    """
    Log a message and, if running in Azure DevOps, log a warning issue and
    attempt to send a Slack message.

    This function logs a message with the Python logging library, and if the
    system is running in Azure DevOps (as determined by the
    SYSTEM_PIPELINESTARTTIME environment variable), it also logs a warning
    issue with Azure DevOps and attempts to send a message via Slack to the
    initiating GitHub user. If `message_type` is set to 'warning', the logger
    will log a warning type. If `message_type` is set to 'error', the logger
    will log an error type, and Azure DevOps will also raise an error and stop
    task execution.

    Args:
    - message_type (str): The type of message to log, either 'warning' or
        'error'.
    - message (str): The message to be logged.
    - slack_recipient (str): The name or ID of the Slack channel or user to
        send the message to (optional).
    - slack_webhook_url (str): The webhook URL for the Slack integration to
        send the message through (optional).

    Returns:
    - None
    """
    global errors_detected

    is_ado = os.getenv("SYSTEM_PIPELINESTARTTIME")
    if is_ado:
        if message_type == "warning":
            # Attempt to send slack message
            # log_message_slack(slack_recipient, slack_webhook_url, message, message_type)
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


def terraform_version_checker(terraform_version, config, current_date):
    # Get the date after which Terraform versions are no longer supported
    end_support_date_str = config["terraform"]["terraform"]["date_deadline"]
    end_support_date = datetime.datetime.strptime(end_support_date_str, "%Y-%m-%d").date()

    # Warn if terraform version is lower than specified & not past deadline.
    if version.parse(terraform_version) < version.parse(
        config["terraform"]["terraform"]["version"]
    ) and current_date <= end_support_date:
        log_message(
            slack_user_id,
            slack_webhook_url,
            "warning",
            f"Detected terraform version {terraform_version} "
            f'is lower than {config["terraform"]["terraform"]["version"]}. '
            f"Please upgrade before deprecation deadline {end_support_date_str}...",
        )
        return True, f'Terraform version {terraform_version} is lower than {config["terraform"]["terraform"]["version"]}. Please upgrade before deprecation deadline {end_support_date_str}.'

    # Error if terraform version lower than specified & passed deadline.
    if version.parse(terraform_version) < version.parse(
        config["terraform"]["terraform"]["version"]
    ) and current_date > end_support_date:
        log_message(
            slack_user_id,
            slack_webhook_url,
            "error",
            f"Terraform version {terraform_version} is no longer supported after deprecation deadline {end_support_date_str}. "
            "Please upgrade...",
        )
        return False, f"Terraform version {terraform_version} is no longer supported after deprecation deadline {end_support_date_str}. Please upgrade."

def transform_environment_components(environment_components=None):
    components_dict = {'components': {}}

    for item in environment_components['environment_components']:
        component = item.pop('component')  # Remove the component from the item and store it
        if component not in components_dict['components']:
            components_dict['components'][component] = []  # Initialize a new list for this component
        components_dict['components'][component].append(item)  # Add the item to the component's list

    print(json.dumps(components_dict, indent=4, sort_keys=True))
    
    return components_dict


def main():
    # initialise array of warnings/errors
    output_file = "nagger_output.json"

    # Get the current date
    current_date = datetime.date.today()
    # Retrieve HMCTS github to slack user mappings
    hmcts_github_slack_user_mappings = get_hmcts_github_slack_user_mappings()
    # Attempt to retrieve github username
    github_user = os.getenv("BUILD_SOURCEVERSIONAUTHOR")
    
    # Attempt to map github user to slack username
    global slack_user_id
    slack_user_id = get_github_slack_user_mapping(
        hmcts_github_slack_user_mappings, github_user
    )
    if not slack_user_id:
        log_message(None, None, "error", "Missing Slack user ID from github mapping. \
                    Please add yourself to the repo at https://github.com/hmcts/github-slack-user-mappings \
                    to proceed")
    
    # Atempt to retrieve slack webhook URL
    global slack_webhook_url
    slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not slack_webhook_url:
        log_message(None, None, "error", "Missing slack webhook URL. Please report via #platops-help on Slack.")

    # Build correct path to terraform binary
    home_dir = os.path.expanduser('~')
    terraform_binary_path = os.path.join(home_dir, '.local', 'bin', 'terraform')

    try:
        # # Try to run `version --json` which is present in tf versions >= 0.13.0
        # result = json.loads(run_command(command))
        # terraform_version = result["terraform_version"]

        # # Use terraform's `terraform_outdated` JSON object to notify if there
        # # is a new terraform version available.
        # if "terraform_outdated" in result and result["terraform_outdated"]:
        #     log_message(
        #         None,
        #         None,
        #         "warning",
        #         f"Detected outdated terraform version: {terraform_version}. Newer version is available.",
        #     )
        try:
            with open(args.environment_components, "r") as f:
                environment_components = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"The file '{args.environment_components}' does not exist.")
        except Exception as e:
            logger.error(f"Error loading {args.environment_components}: {e}")


        # Retrieve the environment variables
        system_default_working_directory = os.getenv('SYSTEM_DEFAULT_WORKING_DIRECTORY')
        build_repo_suffix = os.getenv('BUILD_REPO_SUFFIX')

        # Transform env_components into a dictionary where component is top level
        components_dict = transform_environment_components(environment_components)

        for component in components_dict['components'].keys():
            print(f'component: {component}')
            # Construct the working directory path
            base_directory = os.getenv('BASE_DIRECTORY')
            if not base_directory or base_directory == '':
                working_directory = f"{system_default_working_directory}/{build_repo_suffix}/components/{component}"
            else:
                working_directory = f"{system_default_working_directory}/{build_repo_suffix}/{base_directory}/{component}"

            # Try to run `tfswitch' and 'terraform version --json` which is present in tf versions >= 0.13.0
            command = ["tfswitch", "-b", terraform_binary_path]
            run_command(command, working_directory)

            command = ["terraform", "version", "--json"]
            result = json.loads(run_command(command, working_directory))
            terraform_version = result["terraform_version"]

            # Load deprecation map
            config = load_file(args.filepath)

            # Check if the file exists
            if os.path.exists(output_file):
                # Read existing data from the file
                with open(output_file, 'r') as file:
                    output_array = json.load(file)
            else:
                # If file does not exist, start with an empty list
                output_array = {}

            # Append warning/error if flagged
            is_warning, error_message = terraform_version_checker(terraform_version, config, current_date)

            if is_warning is True:
                output_array['warning'] = {'error_message': error_message, 'components': []}
                output_array['warning']['components'].append(component)
            else:
                output_array['error'] = {'error_message': error_message, 'components': []}
                output_array['error']['components'].append(component)

            # Write the updated data back to the file
            with open(output_file, 'w') as file:
                json.dump(output_array, file, indent=4)

        with open(output_file, 'r') as file:
            complete_file = json.load(file)
            print(f'complete file: { json.dumps(complete_file, indent=4, sort_keys=True) }')
            log_message_slack(
                slack_user_id,
                slack_webhook_url,
                complete_file
            )
            


        # Handle providers
        terraform_providers = result["provider_selections"]

        for provider in terraform_providers:
            if provider not in config["terraform"]["registry.terraform.io"]:
                log_message(
                    slack_user_id,
                    slack_webhook_url,
                    "warning",
                    f"Provider {provider} is missing from version config. "
                    "Please add it to the config in this file in order to "
                    "compare it's versions.",
                )
                print("warning",
                    f"Provider {provider} is missing from version config. "
                    "Please add it to the config in this file in order to "
                    "compare it's versions.")
            else:
                # Handle providers
                # Get the date after which Terraform versions are no longer supported
                end_support_date_str = config["terraform"]["providers"][provider]["date_deadline"]
                end_support_date = datetime.datetime.strptime(end_support_date_str, "%Y-%m-%d").date()

                # Warn if terraform provider version is lower than specified & not past deadline.
                if version.parse(terraform_providers[provider]) < version.parse(
                    config["terraform"]["providers"][provider]["version"]
                ) and current_date <= end_support_date:
                    log_message(
                        slack_user_id,
                        slack_webhook_url,
                        "warning",
                        f"Detected provider {provider} version "
                        f"{terraform_providers[provider]} "
                        "is lower than "
                        f'{config["terraform"]["providers"][provider]["version"]}. '
                        f"Please upgrade before deprecation deadline {end_support_date_str}...",
                    )
                print(
                        "warning",
                        f"Detected provider {provider} version "
                        f"{terraform_providers[provider]} "
                        "is lower than "
                        f'{config["terraform"]["providers"][provider]["version"]}. '
                        f"Please upgrade before deprecation deadline {end_support_date_str}...",
                    )
                # Error if terraform provider version lower than specified & passed deadline.
                if version.parse(terraform_providers[provider]) < version.parse(
                    config["terraform"]["providers"][provider]["version"]
                ) and current_date > end_support_date:
                    log_message(
                        slack_user_id,
                        slack_webhook_url,
                        "error",
                        f"Detected provider {provider} version "
                        f"{terraform_providers[provider]} "
                        "is lower than "
                        f'{config["terraform"]["providers"][provider]["version"]}. '
                        f"This is no longer supported after deprecation deadline {end_support_date_str}. " 
                        "Please upgrade...",
                    )
                    print(
                        "error",
                        f"Detected provider {provider} version "
                        f"{terraform_providers[provider]} "
                        "is lower than "
                        f'{config["terraform"]["providers"][provider]["version"]}. '
                        f"This is no longer supported after deprecation deadline {end_support_date_str}. " 
                        "Please upgrade...",
                    )

    except JSONDecodeError:
        # Fallback to regex when terraform version <= 0.13.0
        result = run_command(command, working_directory)
        terraform_regex = f"^([Tt]erraform(\\s))(?P<semver>{semver_regex})"
        terraform_version = extract_version(result, terraform_regex)
        log_message(
            slack_user_id,
            slack_webhook_url,
            "error",
            f"Detected terraform version {terraform_version} does not support "
            "checking provider versions in addition to the main binary. "
            "Please upgrade your terraform version to at least v0.13.0",
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