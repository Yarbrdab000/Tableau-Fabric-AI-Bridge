// Tableau-Fabric-AI-Bridge — one-click MCP server deployment to Azure Container Apps.
//
// Provisions a Log Analytics workspace, a Container Apps environment, and the MCP
// server container with external HTTPS ingress and scale-to-zero. Tableau Connected
// App credentials and the MCP API key are stored as Container App secrets.
//
// Deploy from the portal via the "Deploy to Azure" button (see ../../Play1_README.md), or:
//   az deployment group create -g <rg> -f main.bicep -p @main.parameters.json

@description('Azure region for all resources. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Name for the Container App (also used as the public subdomain).')
param containerAppName string = 'tableau-mcp'

@description('Container image to run. Publish your own or use a prebuilt image.')
param containerImage string = 'ghcr.io/yarbrdab000/tableau-fabric-ai-bridge-mcp:latest'

@description('Tableau server/pod URL, e.g. https://10ay.online.tableau.com')
param tableauServer string

@description('Tableau site content URL (the slug in the site URL). Empty = Default site.')
param tableauSite string = ''

@description('Tableau auth mode for the server: jwt (Connected App, recommended) or pat.')
@allowed([
  'jwt'
  'pat'
])
param tableauAuth string = 'jwt'

@description('Connected App client ID (Tableau > Settings > Connected Apps).')
param connectedAppClientId string = ''

@description('Connected App secret ID (a non-sensitive identifier shown in Tableau next to the client ID; the secret VALUE is the sensitive one).')
#disable-next-line secure-secrets-in-params
param connectedAppSecretId string = ''

@description('Connected App secret value.')
@secure()
param connectedAppSecretValue string = ''

@description('Tableau username the server acts as (a Site Admin sees all rows / bypasses RLS).')
param jwtUsername string = ''

@description('PAT name (only if tableauAuth = pat).')
param patName string = ''

@description('PAT secret value (only if tableauAuth = pat).')
@secure()
param patValue string = ''

@description('Shared API key callers must present as "Authorization: Bearer <key>" or the "x-api-key" header. Required so your deployed endpoint is not publicly open. Invent a long random string (e.g. a GUID).')
@secure()
param mcpApiKey string

@description('Minimum replicas. 0 enables scale-to-zero (near-zero idle cost).')
@minValue(0)
@maxValue(5)
param minReplicas int = 0

@description('Maximum replicas.')
@minValue(1)
@maxValue(10)
param maxReplicas int = 2

var logName = '${containerAppName}-logs'
var envName = '${containerAppName}-env'

// Container Apps rejects secrets with empty values, so only include the optional
// Tableau secrets when the operator actually supplied them. The API key is required.
var secretsArray = concat(
  [
    {
      name: 'mcp-api-key'
      value: mcpApiKey
    }
  ],
  empty(connectedAppSecretValue) ? [] : [
    {
      name: 'connected-app-secret-value'
      value: connectedAppSecretValue
    }
  ],
  empty(patValue) ? [] : [
    {
      name: 'pat-value'
      value: patValue
    }
  ]
)

var baseEnv = [
  { name: 'MCP_TRANSPORT', value: 'http' }
  { name: 'PORT', value: '8000' }
  { name: 'TABLEAU_SERVER', value: tableauServer }
  { name: 'TABLEAU_SITE', value: tableauSite }
  { name: 'TABLEAU_AUTH', value: tableauAuth }
  { name: 'TABLEAU_CONNECTED_APP_CLIENT_ID', value: connectedAppClientId }
  { name: 'TABLEAU_CONNECTED_APP_SECRET_ID', value: connectedAppSecretId }
  { name: 'TABLEAU_JWT_USERNAME', value: jwtUsername }
  { name: 'TABLEAU_PAT_NAME', value: patName }
  { name: 'MCP_API_KEY', secretRef: 'mcp-api-key' }
]

var containerEnv = concat(
  baseEnv,
  empty(connectedAppSecretValue) ? [] : [
    { name: 'TABLEAU_CONNECTED_APP_SECRET_VALUE', secretRef: 'connected-app-secret-value' }
  ],
  empty(patValue) ? [] : [
    { name: 'TABLEAU_PAT_VALUE', secretRef: 'pat-value' }
  ]
)

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource managedEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  properties: {
    managedEnvironmentId: managedEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      secrets: secretsArray
    }
    template: {
      containers: [
        {
          name: 'mcp'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: containerEnv
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: 8000
              }
              initialDelaySeconds: 5
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/healthz'
                port: 8000
              }
              initialDelaySeconds: 3
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-scale'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
}

@description('The public base URL of the deployed MCP server.')
output mcpBaseUrl string = 'https://${app.properties.configuration.ingress.fqdn}'

@description('The MCP endpoint to register in Copilot Studio (Streamable HTTP).')
output mcpEndpoint string = 'https://${app.properties.configuration.ingress.fqdn}/mcp'

@description('Health check URL.')
output healthUrl string = 'https://${app.properties.configuration.ingress.fqdn}/healthz'
