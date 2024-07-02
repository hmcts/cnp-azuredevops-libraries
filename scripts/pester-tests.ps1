$PESTER_VERSION=5.6.0

if (-Not (Get-Module -ListAvailable -Name Pester)) {
  Install-Module -Name Pester -MaximumVersion $PESTER_VERSION -Force -Verbose -Scope CurrentUser
}
Invoke-Pester ../ -OutputFormat NUnitXml -OutputFile ./TEST-CI.xml -EnableExit