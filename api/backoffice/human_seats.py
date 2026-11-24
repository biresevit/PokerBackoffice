"""Anonymous observed ring seats, never inferred from tournament registrations.

Non-managed accounts are labelled human; this cannot identify external bots.
Missing minutes and stale/incomplete lobby snapshots are not zero humans.
"""
from datetime import datetime, timedelta, timezone

NOTE = ('Human seats are accounts outside this site\'s managed bot list, including sitting-out seats. '
        'Counts cover observed ring tables, not unique people. Tournament human counts are unavailable. '
        'Partial coverage is shown as a lower bound (≥); gaps mean unknown. '
        'History starts when sampling was enabled. '
        'Human presence can help explain timing, but does not prove that a solver ran.')


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def bucket(value, minutes):
    value = utc(value)
    midnight = value.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + timedelta(minutes=(value.hour * 60 + value.minute) // minutes * minutes)


def current(db, site_id):
    rows = db.rows('''SELECT TOP(1) SampledUtc AS at,Humans AS humans,
        ObservedHumans AS observed_humans,FreshTables AS fresh_tables,TotalTables AS total_tables
        FROM backoffice.HumanSeatSample WHERE SiteId=%s AND MachineId=0
          AND SampledUtc>=DATEADD(second,-180,SYSUTCDATETIME()) ORDER BY SampledUtc DESC''', site_id)
    return {**rows[0], 'at': utc(rows[0]['at'])} if rows else None


def history(db, site_id, start, stop, minutes=60, machine=None):
    # Range and machine ownership are validated by the calling site-scoped endpoint.
    floor = bucket(start, minutes)
    rows = db.rows('''SELECT buckets.BucketUtc AS at,
        AVG(CONVERT(float,CASE WHEN FreshTables>0 THEN ObservedHumans ELSE Humans END)) AS humans,
        MIN(CASE WHEN FreshTables>0 THEN ObservedHumans ELSE Humans END) AS minimum,
        MAX(CASE WHEN FreshTables>0 THEN ObservedHumans ELSE Humans END) AS maximum,
        COUNT(CASE WHEN FreshTables>0 THEN ObservedHumans ELSE Humans END) AS known_samples,
        COUNT(Humans) AS complete_samples,COUNT(*) AS samples,
        MIN(FreshTables) AS fresh_tables,MAX(TotalTables) AS total_tables
        FROM backoffice.HumanSeatSample
        CROSS APPLY(SELECT DATEADD(minute,(DATEDIFF(minute,0,SampledUtc)/%s)*%s,0) AS BucketUtc) buckets
        WHERE SiteId=%s AND MachineId=%s
          AND SampledUtc>=%s AND SampledUtc<%s
        GROUP BY buckets.BucketUtc ORDER BY at''',
        minutes, minutes, site_id, machine or 0,
        start.replace(tzinfo=None), stop.replace(tzinfo=None))
    found = {utc(row['at']): row for row in rows}
    points = []
    at = floor
    while at < stop:
        row = found.get(at, {})
        known = row.get('known_samples', 0)
        points.append({'at': at, 'humans': round(row['humans'], 1) if known else None,
                       'minimum': row.get('minimum'), 'maximum': row.get('maximum'),
                       'known_samples': known, 'samples': row.get('samples', 0),
                       'partial': row.get('complete_samples', known) < known,
                       'fresh_tables': row.get('fresh_tables'), 'total_tables': row.get('total_tables')})
        at += timedelta(minutes=minutes)
    return {'format': 'RING', 'scope': 'site' if machine is None else 'pc_bot_tables',
            'step_minutes': minutes, 'note': NOTE, 'points': points}
