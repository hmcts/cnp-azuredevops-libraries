#!/usr/bin/env bash
# Script to check the current build status of the master/main branch
# This is designed to be run as part of pre-commit checks on PRs
# Returns exit code 1 if the master/main build is failing or in progress, 0 if successful

set -euo pipefail

# Default values
ORGANIZATION="${ORGANIZATION:-hmcts}"
PROJECT="${PROJECT:-$SYSTEM_TEAMPROJECT}"
PAT="${AZURE_DEVOPS_PAT:-$SYSTEM_ACCESSTOKEN}"
PIPELINE_ID="${PIPELINE_ID:-$SYSTEM_DEFINITIONID}"

# Usage function
usage() {
>&2 cat << EOF
--------------------------------------------------------------
Script to check the build status of the master/main branch
--------------------------------------------------------------
Usage: $0 [OPTIONS]

Options:
  -o, --organization    Azure DevOps organization (default: hmcts or \$ORGANIZATION)
  -p, --project         Azure DevOps project (default: \$SYSTEM_TEAMPROJECT or \$PROJECT)
  -i, --pipeline-id     Pipeline definition ID (default: \$SYSTEM_DEFINITIONID or \$PIPELINE_ID)
  -t, --token           Azure DevOps PAT token (default: \$SYSTEM_ACCESSTOKEN or \$AZURE_DEVOPS_PAT)
  -h, --help            Show this help message
EOF
exit 1
}

# Parse command line arguments
args=$(getopt -a -o o:p:i:t:h --long organization:,project:,pipeline-id:,token:,help -- "$@")
if [[ $? -gt 0 ]]; then
    usage
fi

eval set -- ${args}
while :
do
    case $1 in
        -h | --help)           usage                  ; shift   ;;
        -o | --organization)   ORGANIZATION="$2"      ; shift 2 ;;
        -p | --project)        PROJECT="$2"           ; shift 2 ;;
        -i | --pipeline-id)    PIPELINE_ID="$2"       ; shift 2 ;;
        -t | --token)          PAT="$2"               ; shift 2 ;;
        --) shift; break ;;
        *) >&2 echo Unsupported option: $1
            usage ;;
    esac
done

# Validate required parameters
if [ -z "$ORGANIZATION" ] || [ -z "$PROJECT" ] || [ -z "$PIPELINE_ID" ]; then
    echo "------------------------"
    echo "Some values are missing, please supply Organization, Project and Pipeline ID" >&2
    echo "Organization: ${ORGANIZATION:-[not set]}"
    echo "Project: ${PROJECT:-[not set]}"
    echo "Pipeline ID: ${PIPELINE_ID:-[not set]}"
    echo "------------------------"
    usage
fi

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
            >&2 echo "Error: Authentication failed (401). Check PAT token."
            exit 1
        elif [ "$http_code" = "403" ]; then
            >&2 echo "Error: Access forbidden (403). Check permissions."
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
