Get-Module -ListAvailable Pester
Install-Module -Name Pester -MaximumVersion 5.4.1 -Force -Verbose -Scope CurrentUser -SkipPublisherCheck
Invoke-Pester ../ -OutputFormat NUnitXml -OutputFile ./TEST-CI.xml -EnableExit