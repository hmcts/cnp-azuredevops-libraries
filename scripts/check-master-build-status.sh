#!/usr/bin/env bash
# Script to check the current build status of the master/main branch
# Designed to run from Azure DevOps pipelines
# Adds a warning comment to the GitHub PR if the master/main build is failing

set -euo pipefail

# Environment variables from Azure DevOps pipeline
ORGANIZATION="${ORGANIZATION:-hmcts}"
PROJECT="${PROJECT:-$SYSTEM_TEAMPROJECT}"
PAT="${AZURE_DEVOPS_PAT:-$SYSTEM_ACCESSTOKEN}"
PIPELINE_ID="${PIPELINE_ID:-$SYSTEM_DEFINITIONID}"

# GitHub PR information (set by Azure Pipelines when triggered by GitHub PR)
GITHUB_PR_NUMBER="${SYSTEM_PULLREQUEST_PULLREQUESTNUMBER:-}"
BUILD_REPOSITORY_NAME="${BUILD_REPOSITORY_NAME:-}"
BUILD_REASON="${BUILD_REASON:-}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"

# Validate required parameters from ADO pipeline
if [ -z "$ORGANIZATION" ] || [ -z "$PROJECT" ] || [ -z "$PIPELINE_ID" ]; then
    echo "##vso[task.logissue type=error]Missing required Azure DevOps environment variables" >&2
    echo "This script must be run from an Azure DevOps pipeline" >&2
    echo "ORGANIZATION: ${ORGANIZATION:-[not set]}" >&2
    echo "PROJECT: ${PROJECT:-[not set]}" >&2
    echo "PIPELINE_ID: ${PIPELINE_ID:-[not set]}" >&2
    exit 1
fi

# Check if running from a GitHub PR build
IS_PR_BUILD=false
if [ "$BUILD_REASON" = "PullRequest" ] && [ -n "$GITHUB_PR_NUMBER" ] && [ -n "$BUILD_REPOSITORY_NAME" ]; then
    IS_PR_BUILD=true
    echo "Running in GitHub PR context - PR #${GITHUB_PR_NUMBER} in ${BUILD_REPOSITORY_NAME}"
else
    echo "Not running from a GitHub PR build - will skip PR comments"
fi

# Function to add a warning comment to the GitHub PR
add_pr_comment() {
    local message=$1
    
    # Only add comments if running from a PR build
    if [ "$IS_PR_BUILD" = false ]; then
        return 0
    fi
    
    if [ -z "$GITHUB_TOKEN" ]; then
        echo "##vso[task.logissue type=warning]GITHUB_TOKEN not set, cannot add comment to PR"
        return 1
    fi
    
    # GitHub API URL for comments
    local api_url="https://api.github.com/repos/${BUILD_REPOSITORY_NAME}/issues/${GITHUB_PR_NUMBER}/comments"
    
    # Check if a warning comment already exists
    local existing_comments=$(curl -s \
        -H "Authorization: token ${GITHUB_TOKEN}" \
        -H "Accept: application/vnd.github.v3+json" \
        "${api_url}")
    
    # Check if any comment contains the warning marker
    if echo "$existing_comments" | jq -e '.[] | select(.body | contains("[!WARNING]") and contains("branch build is currently"))' > /dev/null 2>&1; then
        echo "Warning comment already exists on PR #${GITHUB_PR_NUMBER}, skipping duplicate"
        return 0
    fi
    
    # Create JSON payload
    local payload=$(jq -n --arg msg "$message" '{body: $msg}')
    
    # Post comment to GitHub
    local response
    response=$(curl -s -w "\n%{http_code}" \
        -X POST \
        -H "Authorization: token ${GITHUB_TOKEN}" \
        -H "Accept: application/vnd.github.v3+json" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "$api_url")
    
    local http_code=$(echo "$response" | tail -n1)
    
    if [ "$http_code" = "201" ]; then
        echo "##vso[task.complete result=SucceededWithIssues;]Warning comment added to PR #${GITHUB_PR_NUMBER}"
        return 0
    else
        echo "##vso[task.logissue type=warning]Failed to add comment to PR (HTTP ${http_code})"
        return 1
    fi
}

# Try to detect master branch by checking both main and master
check_branch_build() {
    local branch=$1
    local api_url="https://dev.azure.com/${ORGANIZATION}/${PROJECT}/_apis/build/builds?api-version=5.1&definitions=${PIPELINE_ID}&\$top=1&statusFilter=completed,inProgress&branchName=refs/heads/${branch}"
    
    local response
    if [ -n "$PAT" ]; then
        response=$(curl -s -w "\n%{http_code}" -u ":${PAT}" "$api_url")
    else
        response=$(curl -s -w "\n%{http_code}" "$api_url")
    fi
    
    # Split response and HTTP code
    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')
    
    # Check HTTP response code
    if [ "$http_code" != "200" ]; then
        if [ "$http_code" = "401" ]; then
            echo "##vso[task.logissue type=error]Authentication failed (401). Check PAT token."
        elif [ "$http_code" = "403" ]; then
            echo "##vso[task.logissue type=error]Access forbidden (403). Check permissions."
        else
            echo "##vso[task.logissue type=warning]Unexpected HTTP status code: ${http_code}"
        fi
        return 1
    fi
    
    # Check if response is valid JSON
    if ! echo "$body" | jq empty 2>/dev/null; then
        echo "##vso[task.logissue type=warning]Response is not valid JSON"
        return 1
    fi
    
    local count=$(echo "$body" | jq '.count // 0')
    
    if [ "$count" -gt 0 ]; then
        echo "$body"
        return 0
    else
        echo ""
        return 1
    fi
}

echo "Checking build status for default branch..."

# Try main first, then master
set +e  # Temporarily disable exit on error for function calls
RESPONSE=$(check_branch_build "main")
main_exit_code=$?
set -e  # Re-enable exit on error

if [ $main_exit_code -eq 0 ] && [ -n "$RESPONSE" ]; then
    MASTER_BRANCH="main"
else
    set +e
    RESPONSE=$(check_branch_build "master")
    master_exit_code=$?
    set -e
    
    if [ $master_exit_code -eq 0 ] && [ -n "$RESPONSE" ]; then
        MASTER_BRANCH="master"
    else
        echo "##vso[task.logissue type=warning]No builds found for main or master branch"
        echo "Cannot determine default branch build status - continuing pipeline"
        exit 0
    fi
fi

echo "Using branch: ${MASTER_BRANCH}"

# Extract build information
BUILD_STATUS=$(echo "$RESPONSE" | jq -r '.value[0].status // "unknown"')
BUILD_RESULT=$(echo "$RESPONSE" | jq -r '.value[0].result // "none"')
BUILD_NUMBER=$(echo "$RESPONSE" | jq -r '.value[0].buildNumber // "unknown"')
BUILD_ID=$(echo "$RESPONSE" | jq -r '.value[0].id // "unknown"')

# Build URL for reference in comments
BUILD_URL="https://dev.azure.com/${ORGANIZATION}/${PROJECT}/_build/results?buildId=${BUILD_ID}"

# Check build status and add PR comment if needed
if [ "$BUILD_STATUS" = "inProgress" ]; then
    echo "${MASTER_BRANCH} build #${BUILD_NUMBER} is in progress"
    WARNING_MESSAGE="[!WARNING]
${MASTER_BRANCH} branch build is currently in progress. Please wait for it to complete and ensure it passes before merging this PR.

Build: [#${BUILD_NUMBER}](${BUILD_URL})"
    add_pr_comment "$WARNING_MESSAGE"
    exit 0
elif [ "$BUILD_STATUS" = "completed" ]; then
    if [ "$BUILD_RESULT" = "succeeded" ]; then
        echo "${MASTER_BRANCH} build #${BUILD_NUMBER} is passing"
        exit 0
    else
        echo "${MASTER_BRANCH} build #${BUILD_NUMBER} failed (${BUILD_RESULT})"
        WARNING_MESSAGE="[!WARNING]
${MASTER_BRANCH} branch build is currently broken. Please fix it before merging this PR.

Build: [#${BUILD_NUMBER}](${BUILD_URL})"
        add_pr_comment "$WARNING_MESSAGE"
        exit 0
    fi
else
    echo "${MASTER_BRANCH} build #${BUILD_NUMBER} has unknown status (${BUILD_STATUS})"
    WARNING_MESSAGE="[!WARNING]
${MASTER_BRANCH} branch build status is unknown. Please check the build status before merging this PR.

Build: [#${BUILD_NUMBER}](${BUILD_URL})"
    add_pr_comment "$WARNING_MESSAGE"
    exit 0
fi
