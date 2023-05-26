# cnp-azuredevops-libraries
Reusable pipeline components for CNP Azure DevOps pipelines

## Terraform workflow templates

The template files below contain steps to add Terraform Init/Plan/Apply/Destroy tasks to a pipeline.

    ├── scripts
    ├── steps
    │   └── terraform-precheck.yaml             # Precheck stage tasks
    │   └── terraform.yaml                      # Terraform plan and apply stage tasks
    ├── tasks
    ├── vars

### Reusing templates:
1. Create the [required folder structure](#required-terraform-folder-structure) in your repository
2. Add the cnp-azure-devops-libraries repository resource as below

   ```yaml

   resources:
     repositories:
     - repository: cnp-azuredevops-libraries
       type: github
       ref: refs/heads/master
       name: hmcts/cnp-azuredevops-libraries
       endpoint: 'hmcts (1)'

   ```
3. Use the vars/input-variables.yaml template to add the common variables to your pipeline.

   Make sure you use the correct syntax when declaring a mixture of regular variables and templates, like below.

   Syntax example
   ```yaml
   variables:
     # a regular variable
     - name: myvariable
       value: myvalue
     # a variable group
     - group: myvariablegroup
     # a reference to a variable template
     - template: myvariabletemplate.yml
   ```
   Full example
   ```yaml
   variables:
     - name: timeoutInMinutes
       value: 60
     - name: agentPool
       value: ubuntu-latest
     - name: build
       value: $(Build.BuildNumber)
     - name: product
       value: cft-platform
     - name: terraformInitSubscription
       value: b8d29n39-8007-49m0-95b8-3c8691e90kb
     - template: vars/input-variables.yaml@cnp-azuredevops-libraries
   ```

   [More information on the correct syntax when using regular variables, variables groups and templates.](https://docs.microsoft.com/en-us/azure/devops/pipelines/process/variables?view=azure-devops&tabs=yaml%2Cbatch#specify-variables)

4. Add the terraform-precheck.yaml template to a `Precheck` stage
5. Add the terraform.yaml template to a `TerraformPlanApply` stage
   > see [Example refactored pipeline](https://github.com/hmcts/azure-platform-terraform/blob/master/azure_pipeline.yaml)
6. First time pipeline run:
   * Run build with the Terraform plan option. State file will be created in new location
   * Copy state file from old location to overwrite new state file
   * Run build with Terraform plan to confirm plan reflects migrated state file
7. Run pipeline with plan/apply option as required

### State file:
* In storage accounts in the `HMCTS-CONTROL` subscription
* Storage account name derived from the resources subscription id as below:
  >'c' + '1st-8th character of subscription id' + '25th-36th character of subscription id' + 'sa'
  _e.g. 'cb72ab7b703b0f2c6a1bbsa'_
* Stored in the 'subscription-tfstate' storage container in the folder path derived as below:
  >'location/product/build repo name/environment/component name/terraform.tfstate'
  _e.g. 'UK South/cft-platform/azure-platform-terraform/sbox/shutter/terraform.tfstate'_

### Required terraform folder structure:
Template requires the below folder structure for the build repository.

    Repo
    ├── components
    │   └── <a> (e.g. network)                             # group of .tf files
    │   │       └── .terraform-version (symlink)           # link to .terraform-version at root level (for local testing)
    │   │       │                                            command: ln -s ../../.terraform-version .terraform-version
    │   │       └── *.tf
    │   └── <n>
    ├── environments                                       # Environment specific .tfvars files
    │   └── <env>
    │   │    └── *.tfvars
    ├── azure_pipeline.yaml
    ├── .terraform-version                                 # terraform version (read by tfenv)

### Multiple regions

Some repositories have separate `tfvars` files based on region i.e. `UK South` or `UK West` and having all enviroment
variables in a single `tfvars` file may not meet the requirement.
If you need to use a different set of variables for your build then you can pass the `multiRegion` parameter and
set this as `true`, the default is `false`.

Using multiple region support requires the below environments folder structure for the build repository.

    Repo
    ├── environments                                       # Environment specific .tfvars files
    │   └── <env>
    │   │    └── <location>.tfvars                         # Region specific tfvars file without spaces e.g. prod-ukwest.tfvars

With this a different variable file will be used. An example can be found in the [hub-panorama repo](https://github.com/hmcts/hub-panorama-terraform).

### tfvars file location

Some repositories do not have the `tfvars` file in the standard location, or do not need `tfvars` file at all. In such cases, the `tfVarsFile` option can be used to specify this

#### a) Custom location of `tfvars` file
If `tfvars` file is in a non-standard location, the `tfVarsFile` option can be used to specify the full path of the `tfvars` file, as shown below
```yaml
tfVarsFile: "$(System.DefaultWorkingDirectory)/$(buildRepoSuffix)/environments/network/${{ parameters.env }}.tfvars"
```
> see [example in aks-cft-deploy repo](https://github.com/hmcts/aks-cft-deploy/blob/main/azure-pipelines.yml)

#### b) No `tfvars` file
If the component does not need a `tfvars` file, then a special `NULL` string (all caps) can be specified for  `tfVarsFile`, as shown below.
```yaml
tfVarsFile: NULL
```
Note: This is different from the terraform reserved word `null` and is essentially a special string to indicate that no `tfvars` file is needed.

> see [example in aks-cft-deploy repo](https://github.com/hmcts/aks-cft-deploy/blob/main/azure-pipelines.yml)

### Override components directory

In a monorepo, it may be needed to override the components folder if there's multiple applications that are built from the same repository. You can pass the `baseDirectory` option to specify the location of the components folder.
```yaml
baseDirectory: "terraform/network/components"
```

### Passing environment variables to terraform template:

You can pass environment variables directly to terraform tasks (plan, apply, destroy)
Which then can be used as variable within terraform code as shown in below example:

```yaml
- template: steps/terraform.yaml@cnp-azuredevops-libraries
  parameters:
    overrideAction: ${{ parameters.overrideAction }}
    environment: ${{ deployment.environment }}
    component: ${{ deployment.component }}
    serviceConnection: ${{ deployment.service_connection }}
    terraformInitSubscription: ${{ variables.terraformInitSubscription }}
    product: ${{ variables.product }}
    terraformEnvironmentVariables:
      TF_VAR_foo: $(bar)
```
In terraform you can then reference this variable as `var.foo`

