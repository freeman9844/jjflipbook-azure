param location string
param tags object
param resourceToken string

@secure()
param adminPassword string

@secure()
param internalApiKey string

@secure()
param sessionSecret string

param backendImage string
param frontendImage string

var backendAppName = 'ca-backend-${resourceToken}'
var frontendAppName = 'ca-frontend-${resourceToken}'
var blobContainerName = 'flipbook-assets'
var cosmosDbName = 'jjflipbook'

// ---------- Identity ----------
resource backendIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-backend-${resourceToken}'
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

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${resourceToken}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ---------- Storage (프라이빗 컨테이너 — SAS URL로 접근) ----------
resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'st${resourceToken}'
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false // MI + User-Delegation SAS만 사용 — 계정 키 차단
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
  }
}

resource defenderForStorage 'Microsoft.Security/defenderForStorageSettings@2025-06-01' = {
  scope: storage
  name: 'current'
  properties: {
    isEnabled: false
    overrideSubscriptionLevelSettings: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 } // 실수 삭제 복구 안전망
  }
}

resource assetsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: blobContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource blobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, backendIdentity.id, 'blobcontrib')
  properties: {
    // Storage Blob Data Contributor
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: backendIdentity.properties.principalId
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
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true // AAD(Managed Identity) 인증만 허용 — 키 기반 접근 차단
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
  name: guid(cosmosAccount.id, backendIdentity.id, 'datacontrib')
  properties: {
    // Cosmos DB Built-in Data Contributor
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: backendIdentity.properties.principalId
    scope: cosmosAccount.id
  }
}

// ---------- Container Apps ----------
resource cae 'Microsoft.App/managedEnvironments@2026-01-01' = {
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
// 백엔드는 internal ingress — 같은 환경 내부에서만 접근 가능한 FQDN
var backendUrl = 'https://${backendAppName}.internal.${cae.properties.defaultDomain}'
var frontendUrl = 'https://${frontendAppName}.${cae.properties.defaultDomain}'

resource backendApp 'Microsoft.App/containerApps@2026-01-01' = {
  name: backendAppName
  location: location
  tags: union(tags, { 'azd-service-name': 'backend' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${backendIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      ingress: {
        external: false // 프론트엔드 프록시만 접근 — 공용 인터넷 차단
        targetPort: 8080
        transport: 'auto'
      }
      secrets: [
        { name: 'admin-password', value: adminPassword }
        { name: 'internal-api-key', value: internalApiKey }
      ]
    }
    template: {
      containers: [
        {
          name: 'backend'
          image: backendImage
          resources: { cpu: json('1.0'), memory: '2Gi' }
          probes: [
            {
              type: 'Startup'
              httpGet: { path: '/healthz', port: 8080 }
              initialDelaySeconds: 3
              periodSeconds: 3
              failureThreshold: 20
            }
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8080 }
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: { path: '/healthz', port: 8080 }
              periodSeconds: 10
              failureThreshold: 3
            }
          ]
          env: [
            { name: 'APP_ENV', value: 'production' }
            { name: 'COSMOS_ENDPOINT', value: cosmosAccount.properties.documentEndpoint }
            { name: 'COSMOS_DB_NAME', value: cosmosDbName }
            { name: 'STORAGE_ACCOUNT_NAME', value: storage.name }
            { name: 'BLOB_CONTAINER_NAME', value: blobContainerName }
            { name: 'AZURE_CLIENT_ID', value: backendIdentity.properties.clientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
            { name: 'ADMIN_PASSWORD', secretRef: 'admin-password' }
            { name: 'INTERNAL_API_KEY', secretRef: 'internal-api-key' }
            { name: 'FRONTEND_URL', value: frontendUrl }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 2
        cooldownPeriod: 60
        pollingInterval: 30
        rules: [
          {
            name: 'http-single'
            http: {
              // PDF 변환 OOM 방지: Cloud Run --concurrency=1 대응
              metadata: { concurrentRequests: '1' }
            }
          }
          {
            name: 'daily-warm-window'
            custom: {
              type: 'cron'
              metadata: {
                timezone: 'Asia/Seoul'
                start: '55 9 * * *'
                end: '5 20 * * *'
                desiredReplicas: '1'
              }
            }
          }
        ]
      }
    }
  }
  dependsOn: [blobContributor, cosmosDataContributor]
}

resource frontendApp 'Microsoft.App/containerApps@2026-01-01' = {
  name: frontendAppName
  location: location
  tags: union(tags, { 'azd-service-name': 'frontend' })
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      ingress: {
        external: true
        targetPort: 3000
        transport: 'auto'
      }
      secrets: [
        { name: 'session-secret', value: sessionSecret }
        { name: 'internal-api-key', value: internalApiKey }
      ]
    }
    template: {
      containers: [
        {
          name: 'frontend'
          image: frontendImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          probes: [
            {
              type: 'Startup'
              httpGet: { path: '/', port: 3000 }
              initialDelaySeconds: 3
              periodSeconds: 3
              failureThreshold: 20
            }
            {
              type: 'Liveness'
              httpGet: { path: '/', port: 3000 }
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: { path: '/', port: 3000 }
              periodSeconds: 10
              failureThreshold: 3
            }
          ]
          env: [
            { name: 'NEXT_PUBLIC_BACKEND_URL', value: backendUrl }
            { name: 'SESSION_SECRET', secretRef: 'session-secret' }
            { name: 'INTERNAL_API_KEY', secretRef: 'internal-api-key' }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 2
        cooldownPeriod: 60
        pollingInterval: 30
        rules: [
          {
            name: 'http'
            http: {
              metadata: { concurrentRequests: '10' }
            }
          }
          {
            name: 'daily-warm-window'
            custom: {
              type: 'cron'
              metadata: {
                timezone: 'Asia/Seoul'
                start: '55 9 * * *'
                end: '5 20 * * *'
                desiredReplicas: '1'
              }
            }
          }
        ]
      }
    }
  }
}

output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
output storageAccountName string = storage.name
output backendUrl string = backendUrl
output frontendUrl string = frontendUrl
