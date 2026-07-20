$PESTER_VERSION=6.0.1

if (-Not (Get-Module -ListAvailable -Name Pester)) {
  Install-Module -Name Pester -MaximumVersion $PESTER_VERSION -Force -Verbose -Scope CurrentUser
}
Invoke-Pester ../ -OutputFormat NUnitXml -OutputFile ./TEST-CI.xml -EnableExit