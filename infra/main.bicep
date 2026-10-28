param name string = 'poker-control-nenad'
param location string = 'westeurope'

resource site 'Microsoft.Web/staticSites@2024-11-01' = {
  name: name
  location: location
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  tags: {
    application: 'PokerBackoffice'
    customer: 'Nenad'
  }
  properties: {}
}

output hostname string = site.properties.defaultHostname
output resourceId string = site.id
