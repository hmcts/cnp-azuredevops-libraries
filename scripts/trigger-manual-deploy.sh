#if kubectl config use-context cft-sbox-00-aks &> /dev/null; then
    echo "SBOX already running"
#else
    echo "Starting SBOX"
    # Trigger the workflow using the GitHub API
    curl -L \
      -X POST \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer $1" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      https://api.github.com/repos/hmcts/auto-shutdown/actions/workflows/manual-start.yaml/dispatches \
      -d '{ "ref": "master",
                 "inputs": {
                   "PROJECT": "SDS",
                   "SELECTED_ENV": "sbox",
                   "AKS-INSTANCES": "All"
                 }
               }'
#fi