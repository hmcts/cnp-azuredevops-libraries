if kubectl config use-context cft-sbox-00-aks &> /dev/null; then
    echo "SBOX already running"
else
    echo "Starting SBOX"
    GITHUB_REPO="hmcts/auto-shutdown"
    WORKFLOW_NAME="manual-start"

    # Trigger the workflow using the GitHub API
    curl -X POST \
      -H "Accept: application/vnd.github.v3+json" \
      -H "Authorization: token $1" \
      "https://api.github.com/repos/$GITHUB_REPO/actions/workflows/$WORKFLOW_NAME/dispatches" \
      -d '{
        "ref": "main",
        "inputs": {
          "Business area": "SDS",
          "Environment": "sbox",
          "Cluster": "All"
        }
      }'
fi