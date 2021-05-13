# cnp-azuredevops-libraries
Reusable pipeline components for CNP Azure DevOps pipelines

 
 
  
  

###Terraform Workflow Templates

The template files below contain steps to add Terraform Init/Plan/Apply/Destroy tasks to a pipeline.
    
    ├── scripts                                  
    ├── steps
    │   └── terraform-precheck.yaml 
    │   └── terraform.yaml
    ├── tasks   
    ├── vars   
  
  
####Reusing templates:
1. Create the repo required folder structure
2. Add the cnp-azure-devops-libraries repository resource
3. Add the terraform-precheck.yaml template to a 'Precheck' stage
4. Add the terraform.yaml template to a 'TerraformPlanApply' stage
   > see [Example pipeline](https://github.com/hmcts/azure-platform-terraform/blob/DTSPO-1188/use-cnp-ado-libraries/azure_pipeline.yaml#L267)
5. First time run:  
   Run pipeline with the Terraform plan option  
   Copy state file from existing to new location  
   Run pipeline with Terraform plan to confirm plan reflects migrated state file  
6. Run pipeline with plan/apply option as required   

  
  
####State file:  
* In a storage account in the HMCTS-CONTROL subscription  
* Storage account name derived from the resources subscription id as below:  
  >'c' + '1st-8th character of subscription id' + '25th-36th character of subscription id' + 'sa'  
  _e.g. 'cb72ab7b703b0f2c6a1bbsa'_  
* Stored in the 'subscription-tfstate' storage container in the folder path derived as below:  
  >'location/product/build repo name/environment/component name/terraform.tfstate'  
  _e.g. 'UK South/cft-platform/azure-platform-terraform/sbox/shutter/terraform.tfstate'_  


  
    
####Required folder structure  
Template requires the below folder structure for the build repository.

    Repo
    ├── components                                         
    │   └── component1 (e.g. network)                      # 
    │   │       └── .terraform-version
    │   └── component2 
    ├── environments                                       # Environment specific settings - .tfvars
    │   └── env
    ├── azure_pipeline.yaml
    ├── .terraform-version                                 # defines terraform version to use by tfenv
    