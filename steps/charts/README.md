# Chart Validation Template

`steps/charts/validate.yaml` — Azure DevOps step template for Helm chart CI validation against a live AKS cluster.

## What it does

1. Authenticates to AKS and ACR
2. Resolves the chart path
3. Manages namespace lifecycle (create / reuse / label)
4. Optionally deletes a pre-existing Helm release before install
5. Runs `helm lint`, `helm install`, `helm test` (with log capture)
6. Cleans up the Helm release and namespace on success

## Usage

```yaml
steps:
  - template: steps/charts/validate.yaml@cnp-azuredevops-libraries
    parameters:
      chartName: my-chart
      chartReleaseName: my-chart-ci
      chartNamespace: my-chart-ci
      createNamespace: true
      valuesFile: ci-values.yaml
```

## Parameters

| Parameter | Default | Description |
|---|---|---|
| `serviceConnection` | `DCD-CFTAPPS-DEV` | Azure service connection for AKS auth |
| `registryServiceConnection` | `azurerm-prod` | Azure service connection for ACR login |
| `acrName` | `hmctsprod` | ACR instance to authenticate against |
| `chartName` | _(required)_ | Chart directory name (relative to `chartPath`) |
| `chartReleaseName` | _(required)_ | Helm release name used for install/test/delete |
| `chartNamespace` | _(required)_ | Kubernetes namespace for the release |
| `chartPath` | `./` | Path to the chart root; combined with `chartName` when not `./` |
| `createNamespace` | `false` | When `true`, enables namespace lifecycle management and post-test cleanup |
| `helmVersion` | `3.17.1` | Helm version to install |
| `helmInstallTimeout` | `120` | Seconds to wait for `helm install` |
| `helmTestTimeout` | `300` | Seconds to wait for `helm test` |
| `helmDeleteWait` | `0` | Seconds to wait after pre-install helm delete |
| `helmInstallWait` | `0` | Seconds to wait after helm install before testing |
| `valuesFile` | `ci-values.yaml` | Values file passed to `helm install` |
| `additionalHelmArgs` | _(empty)_ | Extra args appended to `helm install` |
| `aksResourceGroup` | _(empty)_ | Override AKS resource group (skips auto-detect) |
| `aksCluster` | _(empty)_ | Override AKS cluster name (skips auto-detect) |
| `clustersToCheck` | cft-preview-00/01 | List of clusters to probe for active cluster auto-detection |
| `kubeconformValuesFile` | _(empty)_ | Values file used to render manifests for kubeconform; when empty, the kubeconform step is skipped |
| `kubernetesVersion` | `1.35.0` | Kubernetes version kubeconform validates manifests against |
| `kubeconformVersion` | `v0.6.7` | kubeconform release to install |
| `kubeconformCrdSchemaLocation` | datreeio/CRDs-catalog template | Final fallback `-schema-location` for any CRD not covered by the built-in Kubernetes schemas or the auto-generated ASO schemas below (e.g. KEDA). Override to point at a fork/mirror or a static schema file if a chart's CRD is missing or out of date |
| `generateAsoSchemas` | `false` | Opt-in: locally generate ASO CRD schemas for kubeconform — see [ASO CRD schema generation](#aso-crd-schema-generation) below |
| `asoVersion` | `v2.17.0` | ASO release tag to source local CRD schemas from — see [ASO CRD schema generation](#aso-crd-schema-generation) below |
| `asoSchemaRoot` | `$(Agent.TempDirectory)/aso-schemas` | Local directory the generated ASO schemas are written to |
| `runSnapshotTests` | `false` | Run `helm-unittest` snapshot tests (`tests/snapshot-tests/*.yaml`) |
| `runUnitTests` | `false` | Run `helm-unittest` assertion tests — see [Unit and snapshot tests](#unit-and-snapshot-tests) below |
| `unitTestFile` | _(empty)_ | Restrict `runUnitTests` to a single file — see [Unit and snapshot tests](#unit-and-snapshot-tests) below |
| `helmUnittestValuesFile` | `ci-values-minimal.yaml` | Values file passed to `helm unittest` alongside `valuesFile` |
| `helmUnittestVersion` | `v0.8.0` | `helm-unittest` plugin version to install (case-insensitive comparison; only reinstalls when the installed version differs) |

## Namespace lifecycle (`createNamespace`)

### `createNamespace: false` (default)

No namespace management. Template assumes the namespace exists. Pre-install helm delete runs to clear any stale release.

### `createNamespace: true`

The template inspects the namespace at runtime and sets three pipeline variables:

| Variable | Values | Meaning |
|---|---|---|
| `namespaceCreatedByPipeline` | `true` / `false` | Pipeline created the namespace in this run |
| `namespaceManagedByPipeline` | `true` / `false` | Namespace carries the `cnp.validate/template=true` label from a prior run |
| `deletePreviousRelease` | `true` / `false` | Whether to delete any existing Helm release before install |

### Scenario outcomes

| Scenario | Pre-install helm delete | Post-test helm delete | Namespace delete |
|---|---|---|---|
| `createNamespace=false` | Yes | No | No |
| `createNamespace=true` — namespace **does not exist** | No | Yes | Yes |
| `createNamespace=true` — namespace exists, **pipeline-managed** (label present) | Yes | Yes | No¹ |
| `createNamespace=true` — namespace exists, **unmanaged** (no label) | Yes | Yes | No |

> ¹ Namespace was created by a _previous_ pipeline run (label present, but `namespaceCreatedByPipeline=false` for this run). The pipeline leaves it in place.

**Rule of thumb:** the namespace is only deleted when _this run_ created it **and** the pipeline succeeded. If this run created the namespace but the pipeline failed, the namespace is left intact for debugging. The Helm release is always cleaned up when `createNamespace=true`.

## Namespace labels

When the pipeline creates a namespace it applies:

```
cnp.validate/template=true
cnp.validate/build-id=<Build.BuildId>
```

Labels are applied **only at creation time**. Reusing an existing namespace (managed or unmanaged) never relabels it. The `cnp.validate/template=true` label is how the pipeline identifies namespaces it owns across runs.

## Chart path resolution

| `chartPath` | `chartName` | Resolved target |
|---|---|---|
| `./` | `my-chart` | `my-chart` |
| `helm/` | `my-chart` | `helm/my-chart` |
| `helm/` | `/my-chart` | `helm/my-chart` (leading `/` stripped) |
| `helm` | `my-chart` | `helm/my-chart` (trailing `/` added) |

## ASO CRD schema generation

Charts that deploy Azure Service Operator (ASO) custom resources can validate them with kubeconform without depending on the [datreeio/CRDs-catalog](https://github.com/datreeio/CRDs-catalog), which is sometimes missing or out of date for newer ASO CRDs — and without declaring which ASO CRD groups the chart uses.

This is opt-in via `generateAsoSchemas: true` (default `false`), since not every consumer can or wants to fetch and run the upstream ASO CRD bundle/generator locally. When enabled, and whenever `kubeconformValuesFile` is set, the kubeconform step automatically:

1. Renders the chart once and scans the output for any `apiVersion` ending in `.azure.com` to detect the ASO CRD groups actually in use (e.g. `servicebus.azure.com`) — if none are found, schema generation is skipped
2. Downloads the ASO CRD release bundle for `asoVersion`, and kubeconform's [openapi2jsonschema.py](https://github.com/yannh/kubeconform/blob/master/scripts/openapi2jsonschema.py) generator, fresh each run
3. For each detected group, runs the generator against the bundle to write that group's JSON schemas into `asoSchemaRoot/<group>` — patching the generator's `additional_properties()` in-process first, since the upstream version mistakes a CRD field literally named `properties` for the enclosing object's own `{field name: schema}` map and corrupts it
4. Passes kubeconform `-schema-location` flags for the built-in k8s schemas, the generated ASO schemas, and `kubeconformCrdSchemaLocation` (in that order), so non-ASO CRDs (e.g. KEDA) still fall back to the datreeio catalog

If `generateAsoSchemas` is left `false` (or a chart has no detected ASO CRD groups), kubeconform validates ASO CRDs against `kubeconformCrdSchemaLocation` (`datreeio` by default) same as before this feature existed.

When enabled, no per-chart configuration is required beyond the flag — just bump the pinned `asoVersion` default in this repo when a chart needs newer ASO CRDs, or override it per-call for testing.

### Implementation notes

- The detected-group script variables are named `ASO_GROUPS`/`ASO_GROUP` rather than `GROUPS`/`GROUP` — bash treats `GROUPS` as a special read-only array (the process's Unix group IDs) and silently aborts the script on assignment.
- The upstream ASO CRD bundle and `openapi2jsonschema.py` generator are downloaded fresh each run, so upstream fixes and new CRD-version support land automatically without a version bump in this repo.
- A CRD field can legitimately be named `properties`, so the generator's `additional_properties()` patch only recurses into a `properties` key's *values* (the field schemas), not the key itself — otherwise a field's own schema gets mistaken for the enclosing object's `{field name: schema}` map and corrupted.

### Usage

```yaml
steps:
  - template: steps/charts/validate.yaml@cnp-azuredevops-libraries
    parameters:
      chartName: my-chart
      chartReleaseName: my-chart-ci
      chartNamespace: my-chart-ci
      kubeconformValuesFile: ci-values-kubeconform.yaml
      generateAsoSchemas: true
```

## Unit and snapshot tests

`runSnapshotTests` and `runUnitTests` each install (or reinstall, if the version differs) the `helm-unittest` plugin at `helmUnittestVersion`, then run `helm unittest` with `valuesFile` and `helmUnittestValuesFile`.

- Snapshot tests always run the full `tests/snapshot-tests/*.yaml` set.
- Unit tests run the full `tests/unit-tests/*_test.yaml` set by default, or a single file when `unitTestFile` is set. `unitTestFile` is read via a heredoc rather than a plain variable assignment, to avoid quoting/word-splitting issues with the raw parameter value, and is restricted to `[A-Za-z0-9._-]+` to block path traversal or shell injection (e.g. `../../somefile`, `somefile; rm -rf /`).

## Helm test log capture

The `Helm Test` step runs `helm test` without `--logs`, since that flag does not retrieve logs for Job-based test hooks — only Pod-based ones. The step retrieves logs itself afterwards instead:

1. Looks up test hook resources labelled `app.kubernetes.io/instance=<chartReleaseName>`, preferring Jobs over Pods
2. If no labelled Jobs are found, falls back to matching Job names by the `<chartReleaseName>` prefix, in case the chart's test hooks aren't labelled
3. Streams logs from whichever resource type was found

