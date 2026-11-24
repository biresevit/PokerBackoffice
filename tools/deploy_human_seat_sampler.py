"""Add the reporting timer to the active Azure scheduler package, preserving it.

Retains the current package as a private rollback artifact and changes exactly
two Python files. SQL must be verified with check_human_seat_sql.py first.
Credentials remain in memory. Uses the existing signed-in Azure CLI session.
"""
import hashlib
import copy
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile

from azure.storage.blob import BlobServiceClient
from configure_azure import arm, SUB

ROOT = Path(__file__).resolve().parents[1]
RESOURCE = f'/subscriptions/{SUB}/resourceGroups/poker-backoffice/providers/Microsoft.Web/sites/poker-schedule-controller'
ART = ROOT/'artifacts/human-seats-20261124'


def main():
    ART.mkdir(parents=True, exist_ok=True)
    props = arm('GET', RESOURCE)['properties']
    settings = arm('POST', RESOURCE+'/config/appsettings/list', {})['properties']
    storage = props['functionAppConfig']['deployment']['storage']
    service = BlobServiceClient.from_connection_string(settings[storage['authentication']['storageAccountConnectionStringName']])
    container = service.get_container_client(storage['value'].rstrip('/').rsplit('/', 1)[1])
    blobs = list(container.list_blobs())
    states = sorted((b for b in blobs if b.name.startswith('kudu-state') and b.name.endswith('.json')),
                    key=lambda b:b.last_modified, reverse=True)
    state = json.loads(container.download_blob(states[0].name).readall())
    active = state['ActiveDeploymentId']+'.zip'
    original = container.download_blob(active).readall()
    (ART/'scheduler-before.zip').write_bytes(original)
    with zipfile.ZipFile(io.BytesIO(original)) as z:
        files = {n:z.read(n) for n in z.namelist()}
        metadata = {i.filename:copy.copy(i) for i in z.infolist()}
    before = dict(files)
    source = ROOT.parent/'ScheduleController'
    old_function = files['function_app.py'].decode('utf-8').replace('\r\n','\n')
    new_function = (source/'function_app.py').read_text(encoding='utf-8')
    timer = new_function[new_function.index('@app.timer_trigger(schedule="5 *'):new_function.index('@app.timer_trigger(schedule="%SchedulerSchedule%')]
    assert 'human_seat_history_tick' not in old_function, 'Sampler already deployed; inspect before redeploying'
    anchor = '@app.timer_trigger(schedule="%SchedulerSchedule%'
    assert old_function.count(anchor) == 1
    files['function_app.py'] = old_function.replace(anchor, timer+anchor).encode()
    packages = [n.removesuffix('__init__.py') for n in files if n.endswith('schedule_controller/__init__.py')]
    assert len(packages) == 1, 'Expected one installed scheduler package'
    module_path = packages[0]+'human_seat_history.py'
    files[module_path] = (source/'schedule_controller/human_seat_history.py').read_bytes()
    changed = sorted(n for n in files if files[n] != before.get(n))
    assert set(changed) == {'function_app.py',module_path}, changed
    target = ART/'scheduler-human-seats.zip'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        for n,data in files.items():
            info = metadata.get(n, zipfile.ZipInfo(n))
            if n not in metadata:
                info.create_system = 3
                info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info,data)
    record = {'previous_package':active,'previous_sha256':hashlib.sha256(original).hexdigest(),
              'package_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'changed':changed}
    (ART/'sampler-deployment.json').write_text(json.dumps(record,indent=2))
    # Additive, repeatable schema change. No account/session/entry writes.
    import sys
    sys.path.insert(0,str(ROOT/'api'))
    from backoffice.db import connect, Database
    conn = connect()
    try:
        db = Database(conn)
        for batch in re.split(r'^GO\s*$',(ROOT/'sql/021_human_seat_history.sql').read_text(),flags=re.M):
            if batch.strip(): db.execute(batch)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally: conn.close()
    result = subprocess.run([str(ROOT/'.azure-venv/Scripts/python.exe'),'-m','azure.cli',
        'functionapp','deployment','source','config-zip','-g','poker-backoffice',
        '-n','poker-schedule-controller','--src',str(target),'--build-remote','false','-o','json'],
        capture_output=True,text=True)
    if result.returncode:
        print('Azure deployment failed; SQL is additive and the sampler remains disabled. Inspect CLI response privately.')
        (ART/'deployment-private.log').write_text(result.stdout+'\n'+result.stderr)
        raise SystemExit(1)
    # Refresh all settings immediately before adding the one reporting flag.
    settings = arm('POST', RESOURCE+'/config/appsettings/list', {})['properties']
    settings['HUMAN_SEAT_HISTORY_ENABLED'] = 'enabled'
    arm('PUT', RESOURCE+'/config/appsettings', {'properties':settings})
    print(json.dumps({**record,'deployed':True,'sampler_enabled':True}))


if __name__ == '__main__': main()
