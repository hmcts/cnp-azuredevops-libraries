#!/bin/bash
set -e

if [ -z "$FLUX_ENV" ]; then
  FLUX_ENV=$([[ "$ENV" == "ptl" ]] && echo "ptl-intsvc" || ([[ "$ENV" == "ptlsbox" ]] && echo "sbox-intsvc" || echo "$ENV"))
fi

if [ "$CLUSTER" == "All" ]; then
  cluster_numbers=$(az aks list --output tsv --query '[].name' | sed -n "s/${CLUSTER_PREFIX}-${ENV}-\([0-9][0-9]\)-aks/\1/p")
else
  cluster_numbers="$CLUSTER"
fi

for c in $cluster_numbers; do
  ISSUER_URL=$(az aks show \
    -n ${CLUSTER_PREFIX}-${ENV}-${c}-aks \
    -g ${CLUSTER_PREFIX}-${ENV}-${c}-rg \
    --query "oidcIssuerProfile.issuerUrl" -otsv)

  if [ -n "$ISSUER_URL" ]; then
    echo "Issuer URL for cluster ${c}: ${ISSUER_URL}"
    file_path="apps/flux-system/${FLUX_ENV}/${c}/kustomize.yaml"
    sed -i -e "s/ISSUER_URL:.*/ISSUER_URL: \"$(echo "$ISSUER_URL" | sed 's/[\/&]/\\&/g')\"/g" "$file_path"
  fi
done

if [[ -n $(git status -s) ]]; then
  git diff .
  git config --global user.email github-platform-operations@HMCTS.NET
  git config --global user.name "hmcts-platform-operations"
  git add .
  git commit -m "Updating OIDC Issuer URL for $CLUSTER cluster(s) in $FLUX_ENV"
  git remote set-url origin "https://hmcts-platform-operations:${GIT_TOKEN}@github.com/hmcts/${FLUX_CONFIG_REPO}.git"
  git pull origin master --rebase
  for i in {1..5}; do
    git push --set-upstream origin HEAD:master && break || {
      echo "Failed to push, attempt $i of 5 - pulling remote again"
      git pull origin master --rebase
    }
  done
else
  echo "No change to issuer URL, skipping git push..."
fi
