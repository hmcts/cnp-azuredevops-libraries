$RootPath = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path
$TfFiles = @(@((Get-ChildItem $RootPath -filter '*.tf' -Recurse)))

if ($TfFiles.Count -eq 0)
{
  Write-Output 'No Terraform files found in this folder'
}
else
{
  Describe 'Terraform files validation' {
    $TfTestCases = @()
    $TfFiles.ForEach{$TfTestCases += @{Instance = $_}}


    Context "Check for non zero length files" {
      It "<Instance> file is greater than 0" -TestCases $TfTestCases {
        Param($Instance)
        (Get-ChildItem $Instance -Verbose).Length | Should BeGreaterThan 0
      }
    }

    Context "Do not contain the 'Owner' role" {
      It "<Instance> does not have owner role" -TestCases $TfTestCases {
          Param($Instance)
           ((Get-Content -raw $Instance) | Select-String -Pattern "role_definition_name.*=.*Owner" ) | should BeNullOrEmpty
      }
    }

    $TfFolderTestCases=@()
    ((($TfFiles).DirectoryName | Select-Object -Unique)).ForEach{$TfFolderTestCases += @{Instance = $_}}
      Context "Are correctly formatted" {
        It "All files in <Instance> are correctly formatted" -TestCases $TfFolderTestCases {
          Param($Instance)
          Invoke-Expression "terraform fmt -check=true $Instance"  | should BeNullOrEmpty
      }
    }
  }
}