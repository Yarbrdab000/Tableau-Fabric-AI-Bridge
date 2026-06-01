<#
.SYNOPSIS
  Deploy the Tableau-Fabric-AI-Bridge MCP server to Azure Container Apps.

.DESCRIPTION
  CLI alternative to the "Deploy to Azure" button. Requires the Azure CLI
  (`az login` first). The container image must already be published (the GitHub
  Action publishes it to GHCR; or build it yourself with `az acr build`).

.EXAMPLE
  ./deploy.ps1 -ResourceGroup RY-fabric-demo `
               -TableauServer https://10ay.online.tableau.com `
               -TableauSite my-site `
               -ConnectedAppClientId <id> -ConnectedAppSecretId <id> `
               -ConnectedAppSecretValue <value> -JwtUsername admin@company.com `
               -McpApiKey (New-Guid).Guid
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$ResourceGroup,
  [string]$Location = "eastus",
  [string]$ContainerImage = "ghcr.io/yarbrdab000/tableau-fabric-ai-bridge-mcp:latest",
  [Parameter(Mandatory = $true)][string]$TableauServer,
  [string]$TableauSite = "",
  [ValidateSet("jwt", "pat")][string]$TableauAuth = "jwt",
  [string]$ConnectedAppClientId = "",
  [string]$ConnectedAppSecretId = "",
  [string]$ConnectedAppSecretValue = "",
  [string]$JwtUsername = "",
  [string]$PatName = "",
  [string]$PatValue = "",
  [string]$McpApiKey = "",
  [int]$MinReplicas = 0,
  [int]$MaxReplicas = 2
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Deploying MCP server to resource group '$ResourceGroup'..." -ForegroundColor Cyan

$result = az deployment group create `
  --resource-group $ResourceGroup `
  --template-file "$here/main.bicep" `
  --parameters `
    location=$Location `
    containerImage=$ContainerImage `
    tableauServer=$TableauServer `
    tableauSite=$TableauSite `
    tableauAuth=$TableauAuth `
    connectedAppClientId=$ConnectedAppClientId `
    connectedAppSecretId=$ConnectedAppSecretId `
    connectedAppSecretValue=$ConnectedAppSecretValue `
    jwtUsername=$JwtUsername `
    patName=$PatName `
    patValue=$PatValue `
    mcpApiKey=$McpApiKey `
    minReplicas=$MinReplicas `
    maxReplicas=$MaxReplicas `
  --query properties.outputs -o json | ConvertFrom-Json

Write-Host ""
Write-Host "Deployment complete." -ForegroundColor Green
Write-Host "MCP endpoint (register this in Copilot Studio):" -ForegroundColor Yellow
Write-Host "  $($result.mcpEndpoint.value)"
Write-Host "Health check:"
Write-Host "  $($result.healthUrl.value)"
