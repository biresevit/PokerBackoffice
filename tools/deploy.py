"""Deploy static files and managed Python API. Tokens remain in process memory."""
import os
from pathlib import Path
import subprocess
from configure_azure import az

ROOT=Path(__file__).resolve().parents[1]
subprocess.run([str(ROOT/".venv/Scripts/python.exe"),str(ROOT/"tools/build.py")],check=True)
subprocess.run([str(ROOT/".venv/Scripts/python.exe"),str(ROOT/"tools/package_api.py")],check=True)
token=az("staticwebapp","secrets","list","--name","poker-control-nenad","--resource-group","poker-backoffice")["properties"]["apiKey"]
node=next((ROOT/"artifacts/tooling").glob("node-v22.*-win-x64/node.exe"))
env=os.environ.copy()
env["PATH"]=str(node.parent)+os.pathsep+env["PATH"]
env["SWA_CLI_DEPLOYMENT_TOKEN"]=token
env["SWA_CLI_TELEMETRY_ENABLED"]="false"
cli=ROOT/"artifacts/tooling/swa/node_modules/@azure/static-web-apps-cli/dist/cli/bin.js"
result=subprocess.run([str(node),str(cli),"deploy","frontend","--api-location","api",
    "--api-language","python","--api-version","3.11","--env","production"],cwd=ROOT,env=env)
raise SystemExit(result.returncode)
