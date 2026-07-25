targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('azd 환경 이름')
param environmentName string

@minLength(1)
@description('배포 리전')
param location string

@secure()
param adminPassword string

@secure()
param internalApiKey string

@secure()
param sessionSecret string

var tags = { 'azd-env-name': environmentName }

resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'resources'
  scope: rg
  params: {
    location: location
    tags: tags
    resourceToken: toLower(uniqueString(subscription().id, environmentName, location))
    adminPassword: adminPassword
    internalApiKey: internalApiKey
    sessionSecret: sessionSecret
  }
}

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.acrLoginServer
output COSMOS_ENDPOINT string = resources.outputs.cosmosEndpoint
output COSMOS_DB_NAME string = 'jjflipbook'
output STORAGE_ACCOUNT_NAME string = resources.outputs.storageAccountName
output BLOB_CONTAINER_NAME string = 'flipbook-assets'
output NEXT_PUBLIC_BACKEND_URL string = resources.outputs.backendUrl
output FRONTEND_URL string = resources.outputs.frontendUrl
