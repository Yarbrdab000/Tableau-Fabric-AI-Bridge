@description('Name for the Logic App')
param logic_app_name string = 'tableau-vds-logic-app'

resource logicApp 'Microsoft.Logic/workflows@2017-07-01' = {
  name: logic_app_name
  location: resourceGroup().location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    state: 'Enabled'
    definition: {
      '$schema': 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
      contentVersion: '1.0.0.0'
      parameters: {}
      triggers: {}
      actions: {}
      outputs: {}
    }
    parameters: {}
  }
}

output logic_app_name string = logicApp.name
output logic_app_principal_id string = logicApp.identity.principalId
output next_step string = 'Copy the principal ID above. Go to your Key Vault -> Access control (IAM) -> Add role assignment -> Key Vault Secrets User -> paste the principal ID. Wait 2-3 minutes, then run deploy_connection.bicep.'
