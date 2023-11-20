#if kubectl config use-context cft-sbox-00-aks &> /dev/null; then
#    echo "SBOX already running"
#else
    echo "Starting Auto shutdown workflows ..."
    PROJECTS=("SDS" "CFT")
    ENVIRONMENTS=("sbox")
    # Trigger the workflow using the GitHub API
    for project in "${PROJECTS[@]}"; do
      for env in "${ENVIRONMENTS[@]}"; do
         echo "[info] triggering auto shutdown workflow for $project in $env ..."
         curl -L \
               -X POST \
               -H "Accept: application/vnd.github+json" \
               -H "Authorization: Bearer $1" \
               -H "X-GitHub-Api-Version: 2022-11-28" \
               https://api.github.com/repos/hmcts/auto-shutdown/actions/workflows/manual-start.yaml/dispatches \
               -d '{ "ref": "master",
                          "inputs": {
                            "PROJECT": "$project",
                            "SELECTED_ENV": "$env",
                            "AKS-INSTANCES": "All"
                          }
               }'

      done
    done
    # Trigger the workflow using the GitHub API
#fi