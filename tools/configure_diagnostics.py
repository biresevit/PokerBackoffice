"""Configure private log storage, seven-day retention and server-side SAS signing."""
import os
from urllib.error import HTTPError
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError
from configure_azure import az,arm,RESOURCE

raw=os.environ['StorageConnString'];service=BlobServiceClient.from_connection_string(raw)
container=service.get_container_client('machine-diagnostics')
try:container.create_container()
except ResourceExistsError:pass
container.set_container_access_policy(signed_identifiers={},public_access=None)
accounts=az('storage','account','list','--query',f"[?name=='{service.account_name}'].{{id:id}}")
if len(accounts)!=1:raise RuntimeError('Diagnostic storage account was not found in the current subscription')
path=accounts[0]['id']+'/managementPolicies/default'
try:policy=arm('GET',path,api_version='2023-05-01')['properties']['policy']
except HTTPError as error:
    if error.code!=404:raise
    policy={'rules':[]}
rule={'enabled':True,'name':'poker-machine-diagnostics-seven-days','type':'Lifecycle','definition':{
    'filters':{'blobTypes':['blockBlob'],'prefixMatch':['machine-diagnostics/']},
    'actions':{'baseBlob':{'delete':{'daysAfterModificationGreaterThan':7}}}}}
policy['rules']=[r for r in policy.get('rules',[]) if r['name']!=rule['name']]+[rule]
arm('PUT',path,{'properties':{'policy':policy}},api_version='2023-05-01')
settings=arm('POST',RESOURCE+'/listAppSettings')['properties']
settings['BACKOFFICE_DIAGNOSTICS_STORAGE']=raw
arm('PUT',RESOURCE+'/config/appsettings',{'properties':settings})
print('Private diagnostic storage configured; per-blob upload/download links and seven-day blob retention enabled. Credentials suppressed.')
