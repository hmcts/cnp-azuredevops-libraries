Get-PSRepository
Register-PSRepository -Default
Install-Module -Name Pester -MaximumVersion 5.4.1 -Force -Verbose -Scope CurrentUser
Invoke-Pester ../ -OutputFormat NUnitXml -OutputFile ./TEST-CI.xml -EnableExit