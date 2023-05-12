$RootPath = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path
$TfFiles = @(@((Get-ChildItem (Get-Item $RootPath).parent -filter '*.tf' -Recurse)))

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
        (Get-ChildItem $Instance -Verbose).Length | should -BeGreaterThan 0
      }
    }

    $TfFolderTestCases=@()
    ((($TfFiles).DirectoryName | Select-Object -Unique)).ForEach{$TfFolderTestCases += @{Instance = $_}}
      Context "Are correctly formatted" {
        It "All files in <Instance> are correctly formatted. By running 'terraform fmt'" -TestCases $TfFolderTestCases {
          Param($Instance)
          Invoke-Expression "terraform fmt -check=true $Instance"  | should -BeNullOrEmpty
      }
    }
  }
}
