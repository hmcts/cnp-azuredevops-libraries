#!/usr/bin/env bash
# Generates local kubeconform JSON schemas for any ASO CRD groups detected in a rendered Helm manifest.
# See steps/charts/README.md#aso-crd-schema-generation for details.

set -euo pipefail

usage() {
  >&2 cat << EOF
------------------------------------------------------------------
Generate local ASO CRD schemas for kubeconform from a rendered chart
------------------------------------------------------------------
Usage: $0 <rendered-manifest-path> <aso-version> <schema-root>
EOF
  exit 1
}

if [ "$#" -ne 3 ]; then
  usage
fi

RENDERED_MANIFEST="$1"
ASO_VERSION="$2"
SCHEMA_ROOT="$3"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ASO_GROUPS=$(grep -h '^apiVersion:' "$RENDERED_MANIFEST" \
  | awk '{print $2}' \
  | cut -d/ -f1 \
  | grep '\.azure\.com$' \
  | sort -u || true)

if [ -z "$ASO_GROUPS" ]; then
  echo "No ASO CRD groups detected in rendered manifest, skipping local schema generation."
  exit 0
fi
echo "Detected ASO CRD groups: $ASO_GROUPS"

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

python3 -m venv "$WORK_DIR/aso-venv"
"$WORK_DIR/aso-venv/bin/pip" install --quiet pyyaml

curl -sfL "https://github.com/Azure/azure-service-operator/releases/download/${ASO_VERSION}/azureserviceoperator_customresourcedefinitions_${ASO_VERSION}.yaml" \
  -o "$WORK_DIR/aso-crds.yaml"

curl -sfL https://raw.githubusercontent.com/yannh/kubeconform/master/scripts/openapi2jsonschema.py \
  -o "$WORK_DIR/openapi2jsonschema.py"

mkdir -p "$SCHEMA_ROOT"

for ASO_GROUP in $ASO_GROUPS; do
  GROUP_DIR="$SCHEMA_ROOT/$ASO_GROUP"
  mkdir -p "$GROUP_DIR"
  (cd "$GROUP_DIR" && "$WORK_DIR/aso-venv/bin/python3" "$SCRIPT_DIR/write-aso-schema.py" "$WORK_DIR/aso-crds.yaml" "$WORK_DIR/openapi2jsonschema.py" "$ASO_GROUP")
done

echo "Generated schema files:"
find "$SCHEMA_ROOT" -type f | sort
