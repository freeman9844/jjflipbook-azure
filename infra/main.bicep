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

@description('Immutable public GHCR image for the backend')
param backendImage string

@description('Immutable public GHCR image for the frontend')
param frontendImage string

var tags = { 'azd-env-name': environmentName, SecurityControl: 'Ignore' }

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
    backendImage: backendImage
    frontendImage: frontendImage
  }
}

output COSMOS_ENDPOINT string = resources.outputs.cosmosEndpoint
output COSMOS_DB_NAME string = 'jjflipbook'
output STORAGE_ACCOUNT_NAME string = resources.outputs.storageAccountName
output BLOB_CONTAINER_NAME string = 'flipbook-assets'
output NEXT_PUBLIC_BACKEND_URL string = resources.outputs.backendUrl
output FRONTEND_URL string = resources.outputs.frontendUrl
