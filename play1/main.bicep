param workflows_tableau_vds_logic_app_name string = 'tableau-vds-logic-app'

@description('Tableau Cloud pod hostname e.g. 10ay.online.tableau.com')
param tableau_pod string = 'YOUR_TABLEAU_POD'

@description('Tableau site contentUrl slug')
param tableau_site string = 'YOUR_TABLEAU_SITE'

@description('Tableau Personal Access Token name')
param tableau_pat_name string = 'YOUR_PAT_NAME'

@description('LUID of the target Tableau published data source')
param tableau_datasource_luid string = 'YOUR_DATASOURCE_LUID'

@description('Name of the Key Vault secret storing the Tableau PAT secret')
param keyvault_secret_name string = 'YOUR_KEYVAULT_SECRET_NAME'

@description('Resource ID of the Key Vault API connection')
param connections_keyvault_externalid string = '/subscriptions/YOUR_SUBSCRIPTION_ID/resourceGroups/YOUR_RESOURCE_GROUP/providers/Microsoft.Web/connections/keyvault'

@description('Managed API resource ID for Key Vault in your region')
param keyvault_managed_api_location string = '/subscriptions/YOUR_SUBSCRIPTION_ID/providers/Microsoft.Web/locations/YOUR_REGION/managedApis/keyvault'

resource logicApp 'Microsoft.Logic/workflows@2017-07-01' = {
  name: workflows_tableau_vds_logic_app_name
  location: resourceGroup().location
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
                    type: 'object'
                    properties: {
                      fieldCaption: {
                        type: 'string'
                      }
                      function: {
                        type: 'string'
                      }
                    }
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
              properties: [
                'inputs'
                'outputs'
              ]
            }
          }
        }
        HTTP: {
          runAfter: {
            Get_secret: ['Succeeded']
          }
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
                site: {
                  contentUrl: tableau_site
                }
              }
            }
          }
          runtimeConfiguration: {
            contentTransfer: {
              transferMode: 'Chunked'
            }
          }
        }
        Parse_JSON: {
          runAfter: {
            HTTP: ['Succeeded']
          }
          type: 'ParseJson'
          inputs: {
            content: '@body(\'HTTP\')'
            schema: {
              type: 'object'
              properties: {
                credentials: {
                  type: 'object'
                  properties: {
                    token: {
                      type: 'string'
                    }
                    site: {
                      type: 'object'
                      properties: {
                        id: {
                          type: 'string'
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        HTTP_1: {
          runAfter: {
            Parse_JSON: ['Succeeded']
          }
          type: 'Http'
          inputs: {
            uri: 'https://${tableau_pod}/api/3.24/sites/@{body(\'Parse_JSON\')?[\'credentials\']?[\'site\']?[\'id\']}/datasources'
            method: 'GET'
            headers: {
              'X-Tableau-Auth': '@{body(\'Parse_JSON\')?[\'credentials\']?[\'token\']}'
              Accept: 'application/json'
            }
          }
          runtimeConfiguration: {
            contentTransfer: {
              transferMode: 'Chunked'
            }
          }
        }
        Parse_JSON_1: {
          runAfter: {
            HTTP_1: ['Succeeded']
          }
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
                          id: {
                            type: 'string'
                          }
                          name: {
                            type: 'string'
                          }
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
          runAfter: {
            Parse_JSON_1: ['Succeeded']
          }
          type: 'Http'
          inputs: {
            uri: 'https://${tableau_pod}/api/v1/vizql-data-service/query-datasource'
            method: 'POST'
            headers: {
              'X-Tableau-Auth': '@{body(\'Parse_JSON\')?[\'credentials\']?[\'token\']}'
              'Content-Type': 'application/json'
            }
            body: {
              datasource: {
                datasourceLuid: tableau_datasource_luid
              }
              query: {
                fields: '@triggerBody()?[\'query_fields\']'
              }
              options: {
                returnFormat: 'OBJECTS'
              }
            }
          }
          runtimeConfiguration: {
            contentTransfer: {
              transferMode: 'Chunked'
            }
          }
        }
        Response: {
          runAfter: {
            HTTP_2: ['Succeeded']
          }
          type: 'Response'
          kind: 'Http'
          inputs: {
            statusCode: 200
            headers: {
              'Content-Type': 'application/json'
            }
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
            id: keyvault_managed_api_location
            connectionId: connections_keyvault_externalid
            connectionName: 'keyvault'
            connectionProperties: {
              authentication: {
                type: 'ManagedServiceIdentity'
              }
            }
          }
        }
      }
    }
  }
}
