import importlib.util
import sys

import yaml

bundle_path, upstream_path, group = sys.argv[1], sys.argv[2], sys.argv[3]

spec = importlib.util.spec_from_file_location("openapi2jsonschema", upstream_path)
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)

def additional_properties(data, skip=False):
    "This recreates the behaviour of kubectl at https://github.com/kubernetes/kubernetes/blob/225b9119d6a8f03fcbe3cc3d590c261965d928d0/pkg/kubectl/validation/schema.go#L312"
    if isinstance(data, dict):
        if "properties" in data and not skip:
            if "additionalProperties" not in data:
                data["additionalProperties"] = False
        for k, v in data.items():
            if k == "properties" and isinstance(v, dict):
                for field_schema in v.values():
                    additional_properties(field_schema)
            else:
                additional_properties(v)
    return data

upstream.additional_properties = additional_properties

with open(bundle_path) as f:
    for doc in yaml.safe_load_all(f):
        if not doc or doc.get("kind") != "CustomResourceDefinition":
            continue
        if doc["spec"]["group"] != group:
            continue
        for version in doc["spec"].get("versions", []):
            schema = version.get("schema", {}).get("openAPIV3Schema")
            if not schema:
                continue
            filename = "{kind}_{version}.json".format(
                kind=doc["spec"]["names"]["kind"], version=version["name"]
            ).lower()
            upstream.write_schema_file(schema, filename)
