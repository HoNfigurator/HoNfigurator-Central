#at top of script
if (!
    #current role
    (New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    #is admin?
    )).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
) {
    #elevate script and exit current non-elevated runtime
    Start-Process `
        -FilePath 'powershell' `
        -ArgumentList (
            #flatten to single array
            '-File', $MyInvocation.MyCommand.Source, $args `
            | %{ $_ }
        ) `
        -Verb RunAs
    exit
}

Write-Host("Current Directory: $PSScriptRoot")
cd $PSScriptRoot
## Install Chocolatey package manager ##
Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1')) 2>&1 | Write-Verbose
cls

Write-Output "
-----------------------------------------------------
HoNfigurator All in One server install script
The launcher will run once the install has completed
-----------------------------------------------------
"

## Install required software with chocolatey - this will also install the dependencies for these programs ##
Write-Output "Installing dependencies from Chocolatey"
choco install python --version=3.10 -y 2>&1 | Write-Verbose  ## Python 3 - to run the HoNfigurator launcher install
choco install git --version=2.37.3 -y 2>&1 | Write-Verbose ## Github Cli - clone the required repos
choco install nssm -y 2>&1 | Write-Verbose ## Non-Sucking Service Manager - for automating server restarts

## Refresh environemnt variables after installation of dependencies ##
$env:ChocolateyInstall = Convert-Path "$((Get-Command choco).Path)\..\.."   
Import-Module "$env:ChocolateyInstall\helpers\chocolateyProfile.psm1"
refreshenv 2>&1 | Write-Verbose

## Clone HoNfigurator files ##
Write-Output "Cloning HoNfigurator Server Manager files"
git clone https://github.com/frankthetank001/HoNfigurator-Central 2>&1 | Write-Verbose

# ask to download HoN
$confirmation = Read-Host "Do you require a clean HoN download? (y/n)"
if ($confirmation -eq 'y') {
    ## Download HoN client ##
    Write-Output "Downloading HoN Client to current directory. This may take some time - 6.5GB"
    Write-Output "Please wait..."
    $HON="Heroes of Newerth x64 - CLEAN"
    $URL="https://honfigurator.app/Heroes%20of%20Newerth%20x64%20-%20CLEAN.zip"
    $hondir="$pwd\$HON"
    Write-Output "URL: $URL"
    $progressPreference = 'silentlyContinue'
    try {
		curl.exe "$URL" -o "$HON.zip"
    } catch {
        Invoke-WebRequest "$URL" -OutFile "$HON.zip"
    }
    ## Extract HoN Client ##
    Write-Output "Extracting HoN Client to current directory"
    ## server binary advisory
    Expand-Archive -Path "$HON.zip" -DestinationPath $pwd 2>&1 | Write-Verbose
    rm "$HON.zip"
    # Write-Config
    Write-Host("Cloning server binaries from https://github.com/wasserver/wasserver...`nThese files are not associated with HoNfigurator.")
    git clone https://github.com/wasserver/wasserver 2>&1 | Write-Verbose
    $WS = '.\wasserver'
    cp $WS\hon_x64.exe, $WS\k2_x64.dll, $WS\proxy.exe, $WS\proxymanager.exe -Destination "$HON"
    cp $WS\cgame_x64.dll, $WS\game_shared_x64.dll, $WS\game_x64.dll -Destination "$HON\game"
    rm $WS -r -force
    Write-Host("Successfully merged wasserver binaries into $HON")
}
# Install python pre-requisites
Write-Output "Installing python dependencies"
try {
    python -m pip install -r .\HoNfigurator-Central\requirements.txt 2>&1 | Write-Verbose
} catch {
    pip install -r .\HoNfigurator-Central\requirements.txt 2>&1 | Write-Verbose
}
$hf = Get-Location
$hf = "$hf\HoNfigurator-Central"
cd $hf
git pull
Write-Output "Honfigurator directory is $hf"
try{
    if ($confirmation -eq 'y') {
        Write-Output "HoN directory is: $hondir"
	    Start-Process honfigurator.exe -hondir $hondir
    } else {
        Start-Process honfigurator.exe
    }
} catch {
	if ($confirmation -eq 'y') {
        Write-Output "HoN directory is $hondir"
	    python main.py -hondir $hondir
    } else {
        python main.py
    }
}
try {
    $WshShell = New-Object -comObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut("$env:UserProfile\Desktop\HoNfigurator.lnk")
    $Shortcut.WorkingDirectory = "$hf"
    $StartMenu = $WshShell.CreateShortcut("$env:UserProfile\Start Menu\Programs\HoNfigurator.lnk")
    $StartMenu.WorkingDirectory = "$hf"
    $Shortcut.TargetPath = "$pwd\honfigurator.exe"
    $StartMenu.TargetPath = "$pwd\honfigurator.exe"
    $Shortcut.Save()
    $StartMenu.Save()
} catch {
    Write-Host "Error creating and pinning shortcuts: $_"
}

Write-Output "Launching HoNfigurator - you may now close this window"
pause