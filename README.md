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
       value: ubuntu-18.04
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
    
