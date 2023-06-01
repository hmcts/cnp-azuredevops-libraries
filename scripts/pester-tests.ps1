Get-PSRepository
Register-PSRepository -Name “PSGallery” -SourceLocation "https://www.powershellgallery.com/api/v2/" -InstallationPolicy Trusted
Install-Module -Name Pester -MaximumVersion 5.4.1 -Force -Verbose -Scope CurrentUser
Invoke-Pester ../ -OutputFormat NUnitXml -OutputFile ./TEST-CI.xml -EnableExit