import io
import json
import sys
import zipfile
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diagnostics.log_signals import summarize


def archive(site_id=1006):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('manifest.json',json.dumps(dict(site_id=site_id,machine_id=5,captured_utc='2026-11-19T12:00:00Z')))
        z.writestr('controller/run/worker.log','CREDENTIAL_EXPIRED password=do-not-expose\nCREDENTIAL_EXPIRED\nTimeoutError')
        z.writestr('pdecision/PDecision.log','CREDENTIAL_EXPIRED secret hand cards')
    return out.getvalue()


def test_no_raw_logs_or_hand_data():
    result=summarize(archive(),1006,5)
    assert result['signals']['CREDENTIAL_EXPIRED']==2
    assert result['signals']['TimeoutError']==1
    assert result['files_scanned']==1
    assert 'do-not-expose' not in json.dumps(result)
    assert 'hand cards' not in json.dumps(result)


def test_archive_scope_required():
    with pytest.raises(ValueError):summarize(archive(1),1006,5)
    with pytest.raises(ValueError):summarize(archive(),1006,99)
