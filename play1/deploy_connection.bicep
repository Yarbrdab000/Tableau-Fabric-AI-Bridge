@description('Name of the existing Logic App to wire up')
param logic_app_name string = 'tableau-vds-logic-app'

@description('Tableau Cloud pod hostname e.g. 10ay.online.tableau.com')
param tableau_pod string = 'YOUR_TABLEAU_POD'

@description('Tableau site contentUrl slug — the part of your Tableau URL after /site/. Leave blank for Tableau Server default site.')
param tableau_site string = 'YOUR_TABLEAU_SITE_CONTENTURLSLUG'

@description('Tableau Personal Access Token name')
param tableau_pat_name string = 'YOUR_PAT_NAME'

@description('LUID of the target Tableau published datasource. Get this from the Tableau REST API: GET /api/3.24/sites/{siteId}/datasources — find your datasource and copy the id field (GUID format e.g. 0b2344cd-0347-400f-8107-e7ed8139abc3). The Play 1 instructions generator notebook resolves this automatically.')
param tableau_datasource_luid string = 'YOUR_DATASOURCE_LUID_GUID'

@description('Name of your Azure Key Vault e.g. my-keyvault')
param keyvault_name string = 'YOUR_KEYVAULT_NAME'

@description('Name of the secret in Key Vault storing the Tableau PAT secret')
param keyvault_secret_name string = 'YOUR_KEYVAULT_SECRET_NAME'

var location = resourceGroup().location
var kv_connection_name = 'keyvault-${location}'

// ── Key Vault API Connection (managed identity) ───────────────────────────────
resource kvConnection 'Microsoft.Web/connections@2016-06-01' = {
  name: kv_connection_name
  location: location
  properties: {
    displayName: 'tableau-kv-connection'
    api: {
      id: subscriptionResourceId('Microsoft.Web/locations/managedApis', location, 'keyvault')
    }
    parameterValueType: 'Alternative'
    alternativeParameterValues: {
      vaultName: keyvault_name
    }
  }
}

// ── Logic App — full workflow definition ──────────────────────────────────────
resource logicApp 'Microsoft.Logic/workflows@2017-07-01' = {
  name: logic_app_name
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    state: 'Enabled'
    definition: {
      '$schema': 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
      contentVersion: '1.0.0.0'
      parameters: {
        '$connections': {
          defaultValue: {}
          type: 'Object'
        }
      }
      triggers: {
        When_an_HTTP_request_is_received: {
          type: 'Request'
          kind: 'Http'
          inputs: {
            schema: {
              type: 'object'
              properties: {
                query_fields: {
                  type: 'array'
                  items: {
                    type: 'string'
                  }
                }
              }
            }
          }
        }
      }
      actions: {
        Get_secret: {
          runAfter: {}
          type: 'ApiConnection'
          inputs: {
            host: {
              connection: {
                name: '@parameters(\'$connections\')[\'keyvault\'][\'connectionId\']'
              }
            }
            method: 'get'
            path: '/secrets/@{encodeURIComponent(\'${keyvault_secret_name}\')}/value'
          }
          runtimeConfiguration: {
            secureData: {
              properties: [ 'inputs', 'outputs' ]
            }
          }
        }
        HTTP: {
          runAfter: { Get_secret: [ 'Succeeded' ] }
          type: 'Http'
          inputs: {
            uri: 'https://${tableau_pod}/api/3.24/auth/signin'
            method: 'POST'
            headers: {
              'Content-Type': 'application/json'
              Accept: 'application/json'
            }
            body: {
              credentials: {
                personalAccessTokenName: tableau_pat_name
                personalAccessTokenSecret: '@{body(\'Get_secret\')?[\'value\']}'
                site: { contentUrl: tableau_site }
              }
            }
          }
          runtimeConfiguration: { contentTransfer: { transferMode: 'Chunked' } }
        }
        Parse_JSON: {
          runAfter: { HTTP: [ 'Succeeded' ] }
          type: 'ParseJson'
          inputs: {
            content: '@body(\'HTTP\')'
            schema: {
              type: 'object'
              properties: {
                credentials: {
                  type: 'object'
                  properties: {
                    token: { type: 'string' }
                    site: {
                      type: 'object'
                      properties: { id: { type: 'string' } }
                    }
                  }
                }
              }
            }
          }
        }
        HTTP_1: {
          runAfter: { Parse_JSON: [ 'Succeeded' ] }
          type: 'Http'
          inputs: {
            uri: 'https://${tableau_pod}/api/3.24/sites/@{body(\'Parse_JSON\')?[\'credentials\']?[\'site\']?[\'id\']}/datasources'
            method: 'GET'
            headers: {
              'X-Tableau-Auth': '@{body(\'Parse_JSON\')?[\'credentials\']?[\'token\']}'
              Accept: 'application/json'
            }
          }
          runtimeConfiguration: { contentTransfer: { transferMode: 'Chunked' } }
        }
        Parse_JSON_1: {
          runAfter: { HTTP_1: [ 'Succeeded' ] }
          type: 'ParseJson'
          inputs: {
            content: '@body(\'HTTP_1\')'
            schema: {
              type: 'object'
              properties: {
                datasources: {
                  type: 'object'
                  properties: {
                    datasource: {
                      type: 'array'
                      items: {
                        type: 'object'
                        properties: {
                          id: { type: 'string' }
                          name: { type: 'string' }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        HTTP_2: {
          runAfter: { Parse_JSON_1: [ 'Succeeded' ] }
          type: 'Http'
          inputs: {
            uri: 'https://${tableau_pod}/api/v1/vizql-data-service/query-datasource'
            method: 'POST'
            headers: {
              'X-Tableau-Auth': '@{body(\'Parse_JSON\')?[\'credentials\']?[\'token\']}'
              'Content-Type': 'application/json'
            }
            body: {
              datasource: { datasourceLuid: tableau_datasource_luid }
              query: { fields: '@triggerBody()?[\'query_fields\']' }
              options: { returnFormat: 'OBJECTS' }
            }
          }
          runtimeConfiguration: { contentTransfer: { transferMode: 'Chunked' } }
        }
        Response: {
          runAfter: { HTTP_2: [ 'Succeeded' ] }
          type: 'Response'
          kind: 'Http'
          inputs: {
            statusCode: 200
            headers: { 'Content-Type': 'application/json' }
            body: '@body(\'HTTP_2\')'
          }
        }
      }
      outputs: {}
    }
    parameters: {
      '$connections': {
        value: {
          keyvault: {
            id: subscriptionResourceId('Microsoft.Web/locations/managedApis', location, 'keyvault')
            connectionId: kvConnection.id
            connectionName: 'keyvault'
            connectionProperties: {
              authentication: { type: 'ManagedServiceIdentity' }
            }
          }
        }
      }
    }
  }
}

output logic_app_name string = logicApp.name
output trigger_url_note string = 'Deployment complete. Go to the Logic App in the Azure portal -> designer -> When an HTTP request is received trigger -> copy the HTTP POST URL.'
