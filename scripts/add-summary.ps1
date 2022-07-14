#comment

[CmdletBinding()]
param (
    [string]
    $owner = "hmcts",
    [string]
    $repo = "azure-platform-terraform",
    [int]
    $pr,
    [string]
    $token,
    [string]
    $inputFile,
    [string]
    $buildId,
    [string]
    $stageName,
    $exitCode,
    $environment,
    [switch]$isPlan

)
<#
.SYNOPSIS
Minimize GitHub Comments, note that I'm aware of the violation of naming conventions but ...
.DESCRIPTION
This function uses the GraphQL API to retrieve and minimize Old comments. This is to avoid having loads of comments in the PR that are no longer relevant.
The way it works is by matching  "Pipeline StageName: <StageName>" in the body of the comment as well as the right author, at the time of writing it seems that the filtering on the api itself is
limited when it comes to PR comments.
Any comments that match will be minimized
.PARAMETER repo
repository where the pull request exists
.PARAMETER pr
Pull Request Number
.PARAMETER token
github PAT
.PARAMETER stageName
Name of the azure pipeline state where this script is running. This is used to match old comments
.PARAMETER pageSize
Number of comments to retrieve from api, this is hardcode to 50, hopefully we don't have a pipeline with more than 50 stages ever
.PARAMETER environment
Name of the environment where this is running. This is used to match old comments
.PARAMETER $author
Who is making the comments, this is hard coded to "hmcts-platform-operations", the headless account.
.EXAMPLE
An example
.NOTES
General notes
#>

function Minimize-Comment {
    param (
        [string]
        $owner = "hmcts",
        [string]
        $repo = "azure-platform-terraform",
        [int]
        $pr,
        [string]
        $token,
        [string]
        $stageName,
        [int]
        $pageSize = 50,
        [string]
        $environment,
        [string]
        $author = "hmcts-platform-operations",
        [string]
        $matchingString
    )

    $headers = @{"Authorization" = "token $token" }
    $headers.Add("Content-Type", "application/json")
    $headers.Add("Accept", "application/vnd.github.v4+json")

    $uri = "https://api.github.com/graphql"

    Write-Host "Post to GraphQL API: Environment: $environment and stageName: $stageName."

    #TODO:Note that I tried to get the formatting a bit better for the graphql queries but I gave up after a few attempts, I'm sure it can be improved.
    $body = "{`"query`":`"{`\n  repository(name: `\`"$repo`\`", owner: `\`"hmcts`\`") {`\n    pullRequest(number: $pr) {`\n      comments(last: $pageSize) {`\n        edges {`\n          node {`\n            id`\n            isMinimized   `\n            body         `\n            author{`\n              login`\n            }`\n          }`\n        }`\n      }`\n    }`\n  }`\n}`",`"variables`":{}}"

    $comments = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -Body $body
    #TODO: should really separate out the getting of data from the actual mimimization as it would allow easy unit testing.
    $comments.data.repository.pullRequest.comments.edges.node | Where-Object { $_.isMinimized -eq $false -and $_.body -match $matchingString -and $_.author.login -eq $author } | ForEach-Object {
        $body = "{`"query`":`"mutation (`$id: String)  {`\n  minimizeComment(input:{subjectId: `$id, clientMutationId:`\`"$((65..90) + (97..122) | Get-Random -Count 5 | ForEach-Object {[char]$_})`\`",classifier:DUPLICATE}){`\nminimizedComment{isMinimized}`\n  }`\n  `\n}`",`"variables`":{`"id`":`"$($_.id)`"}}" ;
        if ($_.body.Length -gt 75) { $shortComment = $_.body.Substring(0, 75) }else { $shortComment = $_.body }
        Write-Host "Minimizing Comment: $($_.id) for StageName: $stageName with Body (75 first chars):$shortComment.";
        Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -Body $body
    }

}

#TODO: Could make this a bit more functional for ease of testing, so $commentBody should be a variable and same for planCommentPrefix

function Get-PlanBody {
    param (
        $environment,
        $inputFile,
        $stageName,
        $buildId
    )

    if (Test-Path $inputFile) {

    Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -Body $body

    $planObj = Get-Content "tf.json" | ConvertFrom-Json
    $resourceChanges = $planObj.resource_changes
    
    $add = ($resourceChanges | Where-Object {$_.change.actions -contains "create"}).length
    $change = ($resourceChanges | Where-Object {$_.change.actions -contains "update"}).length
    $remove = ($resourceChanges | Where-Object {$_.change.actions -contains "delete"}).length
    $totalChanges = $add + $change + $remove
    
    Write-Host "There are $totalChanges total changes ($add to add, $change to change, $remove to remove)"

    }
    else {
        $body = @{"body" = $("$planCommentPrefix had no plan`nSomething has gone wrong see: https://dev.azure.com//hmcts/CNP/_build/results?buildId={0}&view=charleszipp.azure-pipelines-tasks-terraform.azure-pipelines-tasks-terraform-plan" -f $buildId) }
        Write-Host "The inputfile is empty, i.e. no plan so linking to task."
    }

    return $body
}

#It seems that the approved verb is Test or at least that one that best matches
#Note that this uses a similar construct to Either but hopefully by using Result and Error this is clearer than Left and Right.

function Add-GithubComment {
    param (
        $owner,
        $repo,
        $pr,
        $token,
        $stageName,
        $uri,
        $body,
        $environment,
        $matchingString = "Environment: $environment and Pipeline Stage: $stageName"
    )

    try {
        Write-Host "Add New Comment."
    }
    catch {
        Write-Error "Oops something went horribly wrong."
        Write-Error "$_"
    }
}


if ($token.Length -eq 0) {

    Write-Host "No token passed in. stopping."
    exit 0
}

Write-Host "
owner: $owner,
repo: $repo,
pr: $pr,
token: $token,
inputFile: $inputFile,
buildId: $buildId,
stageName: $stageName,
exitCode: $exitCode,
environment: $environment,
isPlan: $isPlan
"

$headers = @{"Authorization" = "token $token" }
$headers.Add("Accept", "application/vnd.github.v4+json")

$uri = "https://api.github.com/repos/hmcts/azure-platform-terraform/issues/1191/comments" 

#So this is a bit of hack that allows us to pass a variable from the pipeline and thus have unique file names per stage, see template-terraform-deploy-stage.yml for more details (Post Scan Results to Github)
if ($isPlan) {

    $planCommentPrefix = "Environment: $environment and Pipeline Stage: $stageName. There are $totalChanges total changes ($add to add, $change to change, $remove to remove)"

    Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -Body $body

    $planObj = Get-Content "tf.json" | ConvertFrom-Json
    $resourceChanges = $planObj.resource_changes
    
    $add = ($resourceChanges | Where-Object {$_.change.actions -contains "create"}).length
    $change = ($resourceChanges | Where-Object {$_.change.actions -contains "update"}).length
    $remove = ($resourceChanges | Where-Object {$_.change.actions -contains "delete"}).length
    $totalChanges = $add + $change + $remove
    
    Write-Host "There are $totalChanges total changes ($add to add, $change to change, $remove to remove)"

    Write-Host "Will Post Plan to $uri."
    $body = Get-PlanBody -inputFile $inputFile -stageName $stageName -buildId $buildId -environment $environment

    Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -Body $body

    #The matching string has case sensitivity off as well as multiline mode on, namely it will try to match on a per line basis
    Add-GithubComment -repo $repo -pr $pr -token $token -stageName $stageName -uri $uri -body $body -environment $environment -matchingString $("(?im)^$planCommentPrefix")
}

    