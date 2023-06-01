Get-Module -ListAvailable Pester
# Pester module seems to have come pre-installed with PowerShell@2 task and installing again may be creating a conflict hence commenting it out
# Install-Module -Name Pester -MaximumVersion 5.4.1 -Force -Verbose -Scope CurrentUser
Invoke-Pester ../ -OutputFormat NUnitXml -OutputFile ./TEST-CI.xml -EnableExit