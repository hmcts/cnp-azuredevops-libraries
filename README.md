# cnp-azuredevops-libraries
Reusable pipeline components for CNP Azure DevOps pipelines

## Designing Reusable Templates
### Use Parameters where possible
Make it clear what data dependencies a step or task requires by definining parameters, instead of just hoping a variable will be present.

Wrong way:
```
# echo-username.yaml

steps:
- script: echo $(username)
```

Correct way:
```
# echo-username.yaml

parameters:
  username: ''

steps:
- script: echo ${{ parameters.username }}
```

To call the template:
```
# call-echo.yaml

steps:
- template: echo-username.yaml
  parameters:
    username: 'Spiderman'
```
or with a variable:
```
# call-echo.yaml

variables:
  username: Spiderman

steps:
- template: echo-username.yaml
  parameters:
    username: $(username)
```
or with another parameter:
```
# call-echo.yaml

parameters:
  username: ''

steps:
- template: echo-username.yaml
  parameters:
    username: ${{ parameters.username }}
```