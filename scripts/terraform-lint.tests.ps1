$RootPath = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path
$TfFiles = @(@((Get-ChildItem (Get-Item $RootPath).parent -filter '*.tf' -Recurse)))

if ($TfFiles.Count -eq 0)
{
  Write-Output 'No Terraform files found in this folder'
}
else
{
  Describe 'Terraform Config' {
    $TfTestCases = @()
    $TfFiles.ForEach{$TfTestCases += @{Instance = $_}}


    Context "When inspected for empty files" {
      It "Should contain <Instance> file with length greater than 0" -TestCases $TfTestCases {
        Param($Instance)
        (Get-ChildItem $Instance -Verbose).Length | should -BeGreaterThan 0
      }
    }

    $TfFolderTestCases=@()
    ((($TfFiles).DirectoryName | Select-Object -Unique)).ForEach{$TfFolderTestCases += @{Instance = $_}}
      Context "When validated for linting errors" {
        It "Should not return any linting errors for files in <Instance> directory" -TestCases $TfFolderTestCases {
          Param($Instance)
          $output = Invoke-Expression "terraform fmt -check=true -diff $Instance"
          $output | ForEach-Object { Write-Output $_ }
          $output | should -BeNullOrEmpty
      }
    }
  }
}
