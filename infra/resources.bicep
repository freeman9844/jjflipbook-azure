param location string
param tags object
param resourceToken string

@secure()
param adminPassword string

@secure()
param internalApiKey string

@secure()
param sessionSecret string

var backendAppName = 'ca-backend-${resourceToken}'
var frontendAppName = 'ca-frontend-${resourceToken}'
var blobContainerName = 'flipbook-assets'
var cosmosDbName = 'jjflipbook'

// ---------- Identity ----------
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${resourceToken}'
  location: location
  tags: tags
}

// ---------- Monitoring ----------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: 'log-${resourceToken}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ---------- Container Registry ----------
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acr${resourceToken}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, identity.id, 'acrpull')
  properties: {
    // AcrPull
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------- Storage (공개 blob 컨테이너) ----------
resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'st${resourceToken}'
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: true
    minimumTlsVersion: 'TLS1_2'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storage
  name: 'default'
}

resource assetsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: blobContainerName
  properties: {
    // 'Container' = 익명 읽기 + 목록 조회 (music API의 blob list에 필요)
    publicAccess: 'Container'
  }
}

resource blobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, identity.id, 'blobcontrib')
  properties: {
    // Storage Blob Data Contributor
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------- Cosmos DB (Serverless) ----------
resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: 'cosmos-${resourceToken}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [
      { locationName: location, failoverPriority: 0, isZoneRedundant: false }
    ]
    capabilities: [
      { name: 'EnableServerless' }
    ]
  }
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmosAccount
  name: cosmosDbName
  properties: {
    resource: { id: cosmosDbName }
  }
}

var cosmosContainers = [
  { name: 'users', pk: '/id' }
  { name: 'folders', pk: '/id' }
  { name: 'flipbooks', pk: '/id' }
  { name: 'overlays', pk: '/bookId' }
]

resource containers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = [
  for c in cosmosContainers: {
    parent: cosmosDb
    name: c.name
    properties: {
      resource: {
        id: c.name
        partitionKey: { paths: [c.pk], kind: 'Hash' }
      }
    }
  }
]

resource cosmosDataContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, identity.id, 'datacontrib')
  properties: {
    // Cosmos DB Built-in Data Contributor
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: identity.properties.principalId
    scope: cosmosAccount.id
  }
}

// ---------- Container Apps ----------
resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${resourceToken}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// FE/BE 상호 URL은 앱 이름 + defaultDomain으로 결정적으로 계산 (순환 참조 없음)
var backendUrl = 'https://${backendAppName}.${cae.properties.defaultDomain}'
var frontendUrl = 'https://${frontendAppName}.${cae.properties.defaultDomain}'
var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

resource backendApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: backendAppName
  location: location
  tags: union(tags, { 'azd-service-name': 'backend' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
      }
      registries: [
        { server: acr.properties.loginServer, identity: identity.id }
      ]
      secrets: [
        { name: 'admin-password', value: adminPassword }
        { name: 'internal-api-key', value: internalApiKey }
      ]
    }
    template: {
      containers: [
        {
          name: 'backend'
          image: placeholderImage
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'COSMOS_ENDPOINT', value: cosmosAccount.properties.documentEndpoint }
            { name: 'COSMOS_DB_NAME', value: cosmosDbName }
            { name: 'STORAGE_ACCOUNT_NAME', value: storage.name }
            { name: 'BLOB_CONTAINER_NAME', value: blobContainerName }
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'ADMIN_PASSWORD', secretRef: 'admin-password' }
            { name: 'INTERNAL_API_KEY', secretRef: 'internal-api-key' }
            { name: 'FRONTEND_URL', value: frontendUrl }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 2
        rules: [
          {
            name: 'http-single'
            http: {
              // PDF 변환 OOM 방지: Cloud Run --concurrency=1 대응
              metadata: { concurrentRequests: '1' }
            }
          }
        ]
      }
    }
  }
  dependsOn: [acrPull, blobContributor, cosmosDataContributor]
}

resource frontendApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: frontendAppName
  location: location
  tags: union(tags, { 'azd-service-name': 'frontend' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      ingress: {
        external: true
        targetPort: 3000
        transport: 'auto'
      }
      registries: [
        { server: acr.properties.loginServer, identity: identity.id }
      ]
      secrets: [
        { name: 'session-secret', value: sessionSecret }
        { name: 'internal-api-key', value: internalApiKey }
      ]
    }
    template: {
      containers: [
        {
          name: 'frontend'
          image: placeholderImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'NEXT_PUBLIC_BACKEND_URL', value: backendUrl }
            { name: 'STORAGE_ACCOUNT_NAME', value: storage.name }
            { name: 'BLOB_CONTAINER_NAME', value: blobContainerName }
            { name: 'SESSION_SECRET', secretRef: 'session-secret' }
            { name: 'INTERNAL_API_KEY', secretRef: 'internal-api-key' }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 2
      }
    }
  }
  dependsOn: [acrPull]
}

output acrLoginServer string = acr.properties.loginServer
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
output storageAccountName string = storage.name
output backendUrl string = backendUrl
output frontendUrl string = frontendUrl
