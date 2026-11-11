"""Read cached SQL statement counters; compare snapshots without changing database rows."""
import argparse,json,sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'api'))
from backoffice.db import session

PATTERNS={
 'Manual-control polling':'FROM scheduler.ManualTableControl c JOIN scheduler.LiveViewRequest',
 'Live-view expiry cleanup':"UPDATE scheduler.LiveViewRequest SET Status='expired'",
 'Worker ownership locks':'SELECT WorkerEpoch,IsReady FROM scheduler.MachineAssignment WITH',
 'Chat heartbeat updates':'UPDATE scheduler.ChatAgent SET WorkerEpoch=',
 'Updater status locking':'SELECT * FROM scheduler.MachineUpdateAgent WITH',
 'Updater heartbeat updates':'UPDATE scheduler.MachineUpdateAgent SET InstanceId=',
 'Updater task lookup':'SELECT t.*,r.Status AS RolloutStatus',
 'Diagnostic request polling':'SELECT TOP(1) * FROM backoffice.MachineLogRequest',
}
p=argparse.ArgumentParser();p.add_argument('--snapshot',type=Path);p.add_argument('--compare',type=Path);args=p.parse_args()
with session() as db:
 rows=db.rows("""SELECT s.execution_count,LEFT(SUBSTRING(t.text,s.statement_start_offset/2+1,
 CASE WHEN s.statement_end_offset=-1 THEN 1200 ELSE (s.statement_end_offset-s.statement_start_offset)/2+1 END),1200) AS statement_text
 FROM sys.dm_exec_query_stats s CROSS APPLY sys.dm_exec_sql_text(s.sql_handle) t WHERE t.dbid=DB_ID() OR t.dbid IS NULL""")
 stamp=db.one('SELECT SYSUTCDATETIME() AS now')['now']
 resources=db.rows('SELECT TOP(4) end_time,avg_cpu_percent FROM sys.dm_db_resource_stats ORDER BY end_time DESC')
counts={name:0 for name in PATTERNS}
for row in rows:
 for name,pattern in PATTERNS.items():
  if pattern in row['statement_text']:counts[name]+=row['execution_count'];break
result={'stamp':stamp.isoformat(),'counts':counts}
if args.snapshot:args.snapshot.write_text(json.dumps(result))
if args.compare:
 baseline=json.loads(args.compare.read_text());seconds=(stamp-datetime.fromisoformat(baseline['stamp'])).total_seconds()
 rates={name:round((count-baseline['counts'].get(name,0))*60/seconds,1) for name,count in counts.items()}
 result={'sample_seconds':round(seconds,1),'per_minute':rates,'total_per_minute':round(sum(rates.values()),1)}
 if any(rate<0 for rate in rates.values()):result['warning']='A cached plan was evicted; negative deltas are not valid rates.'
result['cpu_samples']=resources
print(json.dumps(result,default=str))
