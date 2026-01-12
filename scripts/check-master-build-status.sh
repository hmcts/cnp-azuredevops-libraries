#!/usr/bin/env bash
# Script to check the current build status of the master/main branch
# This is designed to be run as part of pre-commit checks on PRs
# Returns exit code 1 if the master/main build is failing or in progress, 0 if successful

set -euo pipefail

# Environment variables from Azure DevOps pipeline
ORGANIZATION="${ORGANIZATION:-hmcts}"
PROJECT="${PROJECT:-$SYSTEM_TEAMPROJECT}"
PAT="${AZURE_DEVOPS_PAT:-$SYSTEM_ACCESSTOKEN}"
PIPELINE_ID="${PIPELINE_ID:-$SYSTEM_DEFINITIONID}"

# Validate required parameters
if [ -z "$ORGANIZATION" ] || [ -z "$PROJECT" ] || [ -z "$PIPELINE_ID" ]; then
    echo "Error: Missing required environment variables" >&2
    echo "ORGANIZATION: ${ORGANIZATION:-[not set]}" >&2
    echo "PROJECT: ${PROJECT:-[not set]}" >&2
    echo "PIPELINE_ID: ${PIPELINE_ID:-[not set]}" >&2
    exit 1
fi

# Try to detect master branch by checking both main and master
check_branch_build() {
    local branch=$1
    echo "Checking branch: ${branch}"
    local api_url="https://dev.azure.com/${ORGANIZATION}/${PROJECT}/_apis/build/builds?api-version=5.1&definitions=${PIPELINE_ID}&\$top=1&statusFilter=completed,inProgress&branchName=refs/heads/${branch}"
    
    echo "Making API call..."
    local response
    if [ -n "$PAT" ]; then
        response=$(curl -s -w "\n%{http_code}" -u ":${PAT}" "$api_url")
    else
        response=$(curl -s -w "\n%{http_code}" "$api_url")
    fi
    
    echo "API call completed"
    # Split response and HTTP code
    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')
    
    echo "HTTP Status Code: ${http_code}"
    
    # Check HTTP response code
    if [ "$http_code" != "200" ]; then
        if [ "$http_code" = "401" ]; then
            echo "Error: Authentication failed (401). Check PAT token."
            echo "Organization: ${ORGANIZATION}"
            echo "Project: ${PROJECT}"
            echo "Pipeline ID: ${PIPELINE_ID}"
            exit 1
        elif [ "$http_code" = "403" ]; then
            echo "Error: Access forbidden (403). Check permissions."
            echo "Organization: ${ORGANIZATION}"
            echo "Project: ${PROJECT}"
            echo "Pipeline ID: ${PIPELINE_ID}"
            exit 1
        fi
        echo ""
        return 1
    fi
    
    # Check if response is valid JSON
    if ! echo "$body" | jq empty 2>/dev/null; then
        echo ""
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
echo "Organization: ${ORGANIZATION}"
echo "Project: ${PROJECT}"
echo "Pipeline ID: ${PIPELINE_ID}"
echo "PAT token present: $([ -n "$PAT" ] && echo "yes" || echo "no")"

# Try main first, then master
RESPONSE=$(check_branch_build "main")
if [ -n "$RESPONSE" ]; then
    MASTER_BRANCH="main"
else
    RESPONSE=$(check_branch_build "master")
    if [ -n "$RESPONSE" ]; then
        MASTER_BRANCH="master"
    else
        echo "Error: No builds found for main or master branch"
        exit 1
    fi
fi

echo "Using branch: ${MASTER_BRANCH}"

# Extract build information
BUILD_STATUS=$(echo "$RESPONSE" | jq -r '.value[0].status // "unknown"')
BUILD_RESULT=$(echo "$RESPONSE" | jq -r '.value[0].result // "none"')
BUILD_NUMBER=$(echo "$RESPONSE" | jq -r '.value[0].buildNumber // "unknown"')
BUILD_ID=$(echo "$RESPONSE" | jq -r '.value[0].id // "unknown"')

echo ""
echo "Latest ${MASTER_BRANCH} branch build:"
echo "  Build Number: ${BUILD_NUMBER}"
echo "  Build ID: ${BUILD_ID}"
echo "  Status: ${BUILD_STATUS}"
echo "  Result: ${BUILD_RESULT}"
echo ""

# Check build status
if [ "$BUILD_STATUS" = "inProgress" ]; then
    echo "Error: ${MASTER_BRANCH} branch build is currently in progress"
    echo "Wait for the build to complete before merging"
    exit 1
elif [ "$BUILD_STATUS" = "completed" ]; then
    if [ "$BUILD_RESULT" = "succeeded" ]; then
        echo "${MASTER_BRANCH} branch build is passing"
        exit 0
    else
        echo "Error: ${MASTER_BRANCH} branch build is not passing (${BUILD_RESULT})"
        echo "Fix the ${MASTER_BRANCH} branch build before merging"
        exit 1
    fi
else
    echo "Error: ${MASTER_BRANCH} branch build status is unknown (${BUILD_STATUS})"
    exit 1
fi
