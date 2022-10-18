Install-Module -Name Pester -MaximumVersion 5.3.3 -Force -Verbose -Scope CurrentUser
Invoke-Pester ../ -OutputFormat NUnitXml -OutputFile ./TEST-CI.xml -EnableExit