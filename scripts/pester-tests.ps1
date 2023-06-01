Get-Module -ListAvailable Pester
# Install-Module -Name Pester -MaximumVersion 5.4.0 -Force -Verbose -Scope CurrentUser
Invoke-Pester ../ -OutputFormat NUnitXml -OutputFile ./TEST-CI.xml -EnableExit