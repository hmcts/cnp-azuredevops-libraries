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
import fnmatch
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


def run_command(command, working_directory, is_tf_switch=False):
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
        if is_tf_switch:
            run_command = subprocess.run(command, capture_output=True, timeout=15)
        else:
            run_command = subprocess.run(command, capture_output=True, stderr=subprocess.STDOUT)
        return run_command.stdout.decode("utf-8")
    except subprocess.TimeoutExpired:
        # get latest stable version if tfswitch hangs
        command = ["tfswitch", "--latest"]
        run_command = subprocess.run(command, capture_output=True, timeout=15)
        return run_command.stdout.decode("utf-8")
    
    except TypeError:
        run_command = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
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


def send_slack_message(webhook, channel, username, icon_emoji, build_origin, build_url, build_id, message):
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
        "text": 'Deprecated Config Report',
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
                        "text": "*Build ID:*\n<" + build_url + "|" + build_id + ">"
                    }
                ]
            }
        ]
    }
    
    if errors_detected:
        if message['error']['failed_init']['error_message']:
            error_message_init = message['error']['failed_init']['error_message']
            error_details_init = '\n'.join(message['error']['failed_init']['components'])

            # Add the warning message block
            slack_data["blocks"].extend([
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": "*Error:*\n" + error_message_init
                        },
                        {
                            "type": "mrkdwn",
                            "text": "*Components:*\n" + error_details_init
                        }
                    ]
                }
            ])

        if message['error']['below_0.13']['error_message']:
            error_message_below = message['error']['below_0.13']['error_message']
            error_details_below = '\n'.join(message['error']['below_0.13']['components'])

            # Add the warning message block
            slack_data["blocks"].extend([
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": "*Error:*\n" + error_message_below
                        },
                        {
                            "type": "mrkdwn",
                            "text": "*Components:*\n" + error_details_below
                        }
                    ]
                }
            ])

        if message['error']['terraform_version']['error_message']:
            error_message_version = message['error']['terraform_version']['error_message']
            error_details_version = '\n'.join(message['error']['terraform_version']['components'])

            # Add the warning message block
            slack_data["blocks"].extend([
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": "*Error:*\n" + error_message_version
                        },
                        {
                            "type": "mrkdwn",
                            "text": "*Message:*\n" + error_details_version
                        }
                    ]
                }
            ])



    if message['terraform_version']['components']:
        # Add the warning message block
        slack_data["blocks"].extend([
            {
                "type": "divider"
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": "*Warning:*\n" + message['terraform_version']['error_message']
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*Components:*\n" + '\n'.join(message['terraform_version']['components'])
                    }
                ]
            }
        ])

    if message['terraform_provider']['provider']:
        providers_info = [
            f"{provider} - {end_support_date}" 
            for provider, end_support_date in message['terraform_provider']['provider'].items()
        ]
        # Add the warning message block
        slack_data["blocks"].extend([
            {
                "type": "divider"
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": "*Warning:*\n" + message['terraform_provider']['error_message']
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*Providers:*\n" + '\n'.join(providers_info)
                    }
                ]
            }
        ])

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

        # stage = os.getenv("SYSTEM_STAGEDISPLAYNAME")
        slack_sender = "PlatOps Terraform Nagger"

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
        
        icon_emoji = ":warning:"

        send_slack_message(
            slack_webhook_url, slack_recipient, slack_sender, icon_emoji, build_origin, build_url, build_id, message
        )


def log_message(message_type, message=None):
    """
    Log a message and, if running in Azure DevOps, log a warning issue.

    This function logs a message with the Python logging library, and if the
    system is running in Azure DevOps (as determined by the
    SYSTEM_PIPELINESTARTTIME environment variable), it also logs a warning
    issue with Azure DevOps. If `message_type` is set to 'warning', the logger
    will log a warning type. If `message_type` is set to 'error', the logger
    will log an error type, and Azure DevOps will also raise an error and stop
    task execution.

    Args:
    - message_type (str): The type of message to log, either 'warning' or
        'error'.
    - message (str): The message to be logged.

    Returns:
    - None
    """
    global errors_detected

    is_ado = os.getenv("SYSTEM_PIPELINESTARTTIME")
    if is_ado:
        if message_type == "warning":
            logger.warning(f"##vso[task.logissue type=warning;] {message}")
        if message_type == "error":
            logger.error(f"##vso[task.logissue type=error;] {message}")
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


def terraform_version_checker(terraform_version, config, current_date, component):
    # Get the date after which Terraform versions are no longer supported
    end_support_date_str = config["terraform"]["terraform"]["date_deadline"]
    end_support_date = datetime.datetime.strptime(end_support_date_str, "%Y-%m-%d").date()

    # Warn if terraform version is lower than specified & not past deadline.
    if version.parse(terraform_version) < version.parse(
        config["terraform"]["terraform"]["version"]
    ) and current_date <= end_support_date:
        log_message(
            "warning",
            f"{component} - Detected terraform version {terraform_version} "
            f'is lower than {config["terraform"]["terraform"]["version"]}. '
            f"Please upgrade before deprecation deadline {end_support_date_str}...",
        )

        message = (
            f"Affected Terraform version(s) is lower than "
            f'{config["terraform"]["terraform"]["version"]}. '
            f"Please upgrade before deprecation deadline {end_support_date_str}."
        )
        return 'warning', message

    # Error if terraform version lower than specified & passed deadline.
    if version.parse(terraform_version) < version.parse(
        config["terraform"]["terraform"]["version"]
    ) and current_date > end_support_date:
        log_message(
            "error",
            f"{component} - Terraform version {terraform_version} is no longer supported after deprecation deadline {end_support_date_str}. "
            "Please upgrade...",
        )

        message = (
            f"Affected Terraform version(s) is no longer supported after deprecation deadline {end_support_date_str}. "
            f"Please upgrade."
        )
        return 'error', message
    
    return True, 'Terraform version(s) up to date'


def terraform_provider_checker(provider, provider_version, config, current_date, component):
    if provider in config["terraform"]:
        # Handle providers
        # Get the date after which Terraform versions are no longer supported
        end_support_date_str = config["terraform"][provider]["date_deadline"]
        end_support_date = datetime.datetime.strptime(end_support_date_str, "%Y-%m-%d").date()

        # Warn if terraform provider version is lower than specified & not past deadline.
        if version.parse(provider_version) < version.parse(
            config["terraform"][provider]["version"]
        ) and current_date <= end_support_date:
            log_message(
                "warning",
                f"{component} - Detected provider {provider} version "
                f"{provider_version} "
                "is lower than "
                f'{config["terraform"][provider]["version"]}. '
                f"Please upgrade before deprecation deadline {end_support_date_str}...",
            )

            message = (
                f"Affected provider version(s) will soon reach deprecation. "
                f"Please upgrade version prior to the deprecation date."
            )
            return 'warning', message, end_support_date_str

        # Error if terraform provider version lower than specified & passed deadline.
        if version.parse(provider_version) < version.parse(
            config["terraform"][provider]["version"]
        ) and current_date > end_support_date:
            log_message(
                "error",
                f"{component} - Detected provider {provider} version "
                f"{provider_version} "
                "is lower than "
                f'{config["terraform"][provider]["version"]}. '
                f"This is no longer supported after deprecation deadline {end_support_date_str}. " 
                "Please upgrade...",
            ) 

            message = (
                f"Affected provider version(s) are "
                f"no longer supported after deprecation deadline " 
                f"Please upgrade."
            ) 
            return 'error', message, end_support_date_str
    return True, 'All providers up to date', ''


def create_working_dir_list(base_directory, system_default_working_directory, build_repo_suffix):
    if not base_directory or base_directory == '':
            is_root_dir = True
            working_directory = f"{system_default_working_directory}/{build_repo_suffix}/"

            if os.path.exists(os.path.join(working_directory, "components")):
                is_root_dir = False
                working_directory = f"{system_default_working_directory}/{build_repo_suffix}/components/"               
    else:
        is_root_dir = False
        working_directory = f"{system_default_working_directory}/{build_repo_suffix}/{base_directory}/"

    if is_root_dir:
        components_list = ['/']
    else:
        # Get the list of all child dir in the specified parent directory
        parent_dir = os.listdir(working_directory)
        # Filter out entries that are directories
        components_list = sorted([child_dir for child_dir in parent_dir if os.path.isdir(os.path.join(working_directory, child_dir)) 
                                  and any(fnmatch.fnmatch(file_name, '*.tf') for file_name in os.listdir(os.path.join(working_directory, child_dir)))])
        
    return working_directory, components_list


def add_error(output_warning, error_message, component, error_type=None, provider=None, end_support_date=None):
    # init error key if needed
    if 'error' not in output_warning:
        output_warning['error'] = {
            'terraform_version': {
                'components': [],
                'error_message': ''
            },
            'terraform_provider': {
            'provider': {},
            'error_message': ''
            },
            'failed_init': {
                'components': [],
                'error_message': ''
            },
            'below_0.13': {
                'components': [],
                'error_message': ''
            }
        }
                
    # log error in appropriate key
    if error_type == 'failed_init':
        # failed_init
        output_warning['error']['failed_init']['error_message'] = error_message
        output_warning['error']['failed_init']['components'].append(component)
    if error_type == 'below_0.13':
        # below_0.13
        output_warning['error']['below_0.13']['error_message'] = error_message
        output_warning['error']['below_0.13']['components'].append(component)
        # provider version
    if error_type == 'provider_version':
        output_warning['terraform_provider']['error_message'] = error_message
        output_warning['terraform_provider']['provider'][provider] = end_support_date
    else:
        # terraform_version
        output_warning['error']['terraform_version']['error_message'] = error_message
        output_warning['error']['terraform_version']['components'].append(component)


def main():
    global slack_user_id
    global slack_webhook_url

    # parse environment variables
    system_default_working_directory = os.getenv('SYSTEM_DEFAULT_WORKING_DIRECTORY')
    build_repo_suffix = os.getenv('BUILD_REPO_SUFFIX')
    base_directory = os.getenv('BASE_DIRECTORY')
    github_user = os.getenv("BUILD_SOURCEVERSIONAUTHOR")
    slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")

    # initialisation
    output_file = "nagger_output.json"
    output_warning = {
        'terraform_version': {
            'components': [],
            'error_message': ''
        },
        'terraform_provider': {
            'provider': {},
            'error_message': ''
        }
    }
    current_date = datetime.date.today()
    
    # ado error if slack webhook url missing
    if not slack_webhook_url:
        log_message("warning", "Missing slack webhook URL. Please report via #platops-help on Slack.")

    # build path to terraform binary
    home_dir = os.path.expanduser('~')
    terraform_binary_path = os.path.join(home_dir, '.local', 'bin', 'terraform')
    # construct working directory (./component/ or $baseDirectory)
    working_directory, components_list = create_working_dir_list(base_directory, system_default_working_directory, build_repo_suffix)
    # load deprecation map
    deprecation_map = load_file(args.filepath)
    
    print('Analysing components...')

    for component in components_list:
        try:
            print(f'component: {component}')
            full_path = f'{working_directory}{component}'

            # fail out loop if terraform version <= 0.13.0
            command = ["tfswitch", "-b", terraform_binary_path]
            run_command(command, full_path, True)
            command = ["terraform", "version", "--json"]
            result = json.loads(run_command(command, full_path))

            ### catch terraform init errors
            command = ["terraform", "init", "-backend=false"]
            output = run_command(command, full_path)
            
            if not 'Terraform has been successfully initialized!' in output:
                # trigger ado console
                log_message( 'error',
                    f'{component} - Terraform init failed. Please see docs for further information: '
                    'https://github.com/hmcts/cnp-azuredevops-libraries?tab=readme-ov-file#required-terraform-folder-structure'
                    )
                # log error & save to file
                error_message = (
                    f'Terraform init failed for specified components. Please see docs for further information: '
                    f'<https://github.com/hmcts/cnp-azuredevops-libraries?tab=readme-ov-file#required-terraform-folder-structure|Docs>'
                    )
                add_error(output_warning, error_message, component, 'failed_init')

                print(output)
                logger.error(f"##vso[task.logissue type=error;] Error returned\n{output}")

            ### rerun version --json to fetch providers post init
            command = ["terraform", "version", "--json"]
            result = json.loads(run_command(command, full_path))

            ### check terraform version against deprecation map
            terraform_version = result["terraform_version"]
            # warning/error logging - terraform_version_checker handles console log
            alert_level, error_message = terraform_version_checker(terraform_version, deprecation_map, current_date, component)
            if alert_level == 'warning':
                output_warning['terraform_version']['error_message'] = error_message
                output_warning['terraform_version']['components'].append(component)
            if alert_level == 'error':
                add_error(output_warning, error_message, component)

            ### check provider versions against deprecation map
            terraform_providers = result["provider_selections"]
            if terraform_providers:
                for provider, provider_version in terraform_providers.items():
                    # warning/error logging - terraform_version_checker handles console log
                    alert_level, error_message, end_support_date_str = terraform_provider_checker(provider, provider_version, deprecation_map, current_date, component)
                    provider = provider.split('/')[-1]
                    if alert_level == 'warning':
                        output_warning['terraform_provider']['error_message'] = error_message
                        if provider not in output_warning['terraform_provider']['provider']:
                            output_warning['terraform_provider']['provider'][provider] = end_support_date_str
                    if alert_level == 'error':
                        add_error(output_warning, error_message, component, 'provider_version', provider, end_support_date_str)

            # write back to file
            with open(output_file, 'w') as file:
                json.dump(output_warning, file, indent=4)
            log_message('group_close')

        ### fallback to regex when terraform version <= 0.13.0
        except JSONDecodeError:
            result = run_command(command, full_path)
            terraform_regex = f"^([Tt]erraform(\\s))(?P<semver>{semver_regex})"
            terraform_version = extract_version(result, terraform_regex)

            # strip preceding "v" for version comparison
            if terraform_version[0].lower() == "v":
                terraform_version = terraform_version[1:]

            # trigger ado console
            log_message(
                "error",
                f"{component} - Detected terraform version {terraform_version} does not support "
                f"checking provider versions in addition to the main binary. "
                f"Please upgrade your terraform version to at least v0.13.0"
            )
            error_message = (
                    f'Please upgrade your terraform version to at least v0.13.0'
                    )
            # log error & save to file
            add_error(output_warning, error_message, component, 'below_0.13')
            with open(output_file, 'w') as file:
                json.dump(output_warning, file, indent=4)

        ### script failues etc
        except Exception as e:
            logger.error("Unknown error occurred")
            raise Exception(e)
        
    ### trigger slack message if we've collated warnings/errors
    with open(output_file, 'r') as file:
        complete_file = json.load(file)
        
    # only slack send if we have collated errors/warnings
    if ('error' in complete_file or
        (complete_file.get('terraform_version', {}).get('components')) or
        (complete_file.get('terraform_provider', {}).get('provider'))):

        slack_user_id = get_github_slack_user_mapping(
            get_hmcts_github_slack_user_mappings(), github_user
        )
        # ado error if slack user id missing
        if not slack_user_id:
            log_message("warning",
                        f"Cannot send slack report: Requires the Github PR author "
                        f"or last commit author to have an entry in https://github.com/hmcts/github-slack-user-mappings "
                        f"This is a self service repo - "
                        f"please review the README, PR & merge your entry and re-run the pipeline."
                        )

        # skip slack message send for renovate/gh apps
        # skip slack message if slack_id is not present
        if slack_user_id and slack_user_id != 'iamabotuser':
            log_message_slack(
                slack_user_id,
                slack_webhook_url,
                complete_file
                )
        
    ### exit code 1 if errors
    if errors_detected:
        raise SystemExit(1)


if __name__ == "__main__":
    main()