import base64
import json
from contextlib import contextmanager
from datetime import datetime, timezone
import pytest
from backoffice.app import Request, handle, principal
from backoffice.store import Context, Store, live_table_sort_key, scheduled_target
from backoffice.validation import Error, parse_csv, stake_bands, windows


@pytest.mark.parametrize("value", [None, [], {}, {"identityProvider":"github"}, {"identityProvider":"aad","userId":"x","userRoles":[]}])
def test_untrusted_identity_rejected(value):
    with pytest.raises(Error) as e:
        principal({"x-ms-client-principal":base64.b64encode(json.dumps(value).encode()).decode()})
    assert e.value.status == 401


def header():
    return {"x-ms-client-principal":base64.b64encode(json.dumps({"identityProvider":"aad","userId":"subject","userRoles":["authenticated"]}).encode()).decode()}


def test_unauthenticated_never_opens_database():
    def fail():
        raise AssertionError("DB accessed")
    assert handle(Request("GET","/api/sites"), fail).status == 401


def test_cross_origin_mutation_rejected():
    assert handle(Request("POST","/api/access-request",header())).status == 403


def test_foreign_customer_rejected_before_site_query():
    class DB:
        def rows(self, sql, *p):
            assert p == ("aad", "subject")
            return [{"id":14004,"name":"Nenad","role":"operator"}]
        def one(self,*a):
            raise AssertionError("Foreign resource queried")
    @contextmanager
    def session():
        yield DB()
    result=handle(Request("GET","/api/sites/1/accounts",header(),{"customer_id":"1"}),session)
    assert result.status == 403


def test_csv_duplicates_rejected():
    with pytest.raises(Error):
        parse_csv('username,profile\nMonica,Maniac\nmonica,Strong Tight')


def test_csv_quoted_names_and_bom():
    assert parse_csv('\ufeffnickname,profile\n"a,b",Strong Balanced')[0] == {"username":"a,b","strategy":5}


def test_malformed_stakes_and_overlapping_schedule():
    with pytest.raises(Error):
        stake_bands({"bands":[None,None,None]})
    with pytest.raises(Error):
        windows({"windows":[{"weekday":1,"start_minute":10,"end_minute":100,"target":56},{"weekday":1,"start_minute":90,"end_minute":120,"target":1}]})


def test_current_scheduled_target_uses_local_weekday_and_minute():
    schedule={"enabled":True,"timezone":"UTC","windows":[
        {"weekday":0,"start_minute":600,"end_minute":660,"target":56}]}
    assert scheduled_target(schedule,datetime(2026,10,26,10,30,tzinfo=timezone.utc))==56
    assert scheduled_target(schedule,datetime(2026,10,26,11,0,tzinfo=timezone.utc))==0
    schedule["enabled"]=False
    assert scheduled_target(schedule,datetime(2026,10,26,10,30,tzinfo=timezone.utc))==0


def test_live_tables_query_excludes_observations_older_than_60_seconds():
    class DB:
        def execute(self, sql, *params):
            assert sql == "EXEC scheduler.ExpireOfflineMachines @CustomerId=%s"
            assert params == (14004,)

        lobby_sql = None

        def one(self, sql, *params):
            if "FROM scheduler.Site" in sql and "LobbyRefreshSeconds" not in sql:
                return {"id":1,"name":"Evenbet","customer_id":14004,"timezone":"Europe/Budapest",
                        "currency":"DEMO","version":1,"enabled":True}
            if "LobbyRefreshSeconds" in sql:
                return {"seconds":15}
            raise AssertionError(sql)

        def rows(self, sql, *params):
            assert params == (1,)
            self.lobby_sql = sql
            return []

    db = DB()
    result = Store(db, Context(14004,"test","subject","operator")).tables(1)
    assert result["items"] == []
    assert "t.ObservedUtc >= DATEADD(SECOND,-60,SYSUTCDATETIME())" in db.lobby_sql


def test_live_table_bot_count_comes_from_current_seats_not_open_entries():
    class DB:
        def execute(self, sql, *params):
            assert params == (14004,)

        def one(self, sql, *params):
            if "FROM scheduler.Site" in sql and "LobbyRefreshSeconds" not in sql:
                return {"id":1,"name":"Evenbet","customer_id":14004,"timezone":"Europe/Budapest",
                        "currency":"DEMO","version":1,"enabled":True}
            if "LobbyRefreshSeconds" in sql:
                return {"seconds":15}
            raise AssertionError(sql)

        def rows(self, sql, *params):
            if "FROM scheduler.LobbyTable" in sql:
                assert "scheduler.Entry" not in sql
                return [{"id":"42","name":"Insurance","game":"NLH","table_type":"RING",
                         "big_blind":2,"currency":"DEMO","seats":6,"occupied":2,
                         "observed":datetime.now(timezone.utc),"snapshot":datetime.now(timezone.utc),
                         "is_open":True}]
            if "FROM scheduler.TableSeat" in sql:
                return [{"seat":0,"username":"monica","stack":100,"bet":0,"in_game":False,
                         "sitting_out":False,"account_id":7,"machine_id":1},
                        {"seat":4,"username":"Human","stack":80,"bet":0,"in_game":False,
                         "sitting_out":False,"account_id":None,"machine_id":None}]
            raise AssertionError(sql)

    result=Store(DB(),Context(14004,"test","subject","operator")).tables(1)
    assert result["items"][0]["occupied"]==2
    assert result["items"][0]["bot_entries"]==1


def test_live_table_default_order_groups_ring_formats_before_tournaments():
    def row(game,table_type,bots=0,occupied=0):
        return {"game":game,"table_type":table_type,"bot_entries":bots,"occupied":occupied,
                "big_blind":1,"name":game+table_type}
    items=[row("NLH","MTT",3,3),row("PLO5","RING"),row("NLH","SNG"),
           row("PLO4","RING"),row("NLH","RING"),row("NLH","RING",2,2)]
    ordered=sorted(items,key=live_table_sort_key)
    assert [(x["game"],x["table_type"]) for x in ordered] == [
        ("NLH","RING"),("NLH","RING"),("PLO4","RING"),("PLO5","RING"),
        ("NLH","SNG"),("NLH","MTT")]
    assert ordered[0]["bot_entries"]==2


def test_site_reads_authorize_without_cleanup_writes():
    class DB:
        def __init__(self):self.reads=[]
        def one(self, sql, *params):
            self.reads.append(params)
            return {"version":1} if params == (1,14004) else None
        def execute(self, sql, *params):
            raise AssertionError('A page read attempted a write')
    db=DB()
    store=Store(db,Context(14004,"test","subject","viewer"))
    store.site(1)
    store.site(1)
    assert db.reads == [(1,14004)]
    with pytest.raises(Error):
        Store(db,Context(1,"test","foreign","viewer")).site(1)
    assert db.reads[-1] == (1,1)


def test_cached_site_never_bypasses_a_fresh_settings_version_check():
    class DB:
        version=1
        def one(self,sql,*params):return {'version':self.version}
    db=DB();store=Store(db,Context(14004,'test','subject','operator'))
    store.site(1);db.version=2
    with pytest.raises(Error) as error:store.site(1,lock=True,version=1)
    assert error.value.status==409


def test_task_result_descriptions_explain_cancellations_and_missing_details():
    from backoffice.store import task_result_description
    assert "target was reduced" in task_result_description({"result_code":"target_reduced"})
    assert "did not record" in task_result_description({"result_code":"ValueError"})
    assert task_result_description({"result_code":"ValueError","result_text":"Insufficient balance"})=="Insufficient balance"


def test_entry_chart_preserves_exact_changes_and_schedule_boundaries():
    from datetime import timedelta
    from backoffice.store import entry_history_points
    start=datetime(2026,10,29,8,tzinfo=timezone.utc)
    schedule={"enabled":True,"timezone":"UTC","windows":[{"weekday":3,"start_minute":480,"end_minute":482,"target":10},{"weekday":3,"start_minute":482,"end_minute":540,"target":20}]}
    join=start+timedelta(seconds=37)
    close=start+timedelta(minutes=3,seconds=12)
    points=entry_history_points(schedule,[(join,close)],start,start+timedelta(minutes=5),5)
    by_time={p["at"]:p for p in points}
    assert by_time[start]["running"]==0
    assert by_time[join]["running"]==1
    assert by_time[start+timedelta(minutes=2)]["scheduled"]==20
    assert by_time[close]["running"]==0
    assert points[-1]["running"]==0


def test_entry_chart_simultaneous_join_close_and_range_start():
    from datetime import timedelta
    from backoffice.store import entry_history_points
    start=datetime(2026,10,29,8,tzinfo=timezone.utc)
    switch=start+timedelta(seconds=30)
    schedule={"enabled":False,"timezone":"UTC","windows":[]}
    points=entry_history_points(schedule,[(start-timedelta(minutes=1),start),(start,switch),(switch,None)],start,start+timedelta(minutes=1),1)
    assert all(p["running"]==1 and p["scheduled"]==0 for p in points)


def test_account_rebuy_chances_are_required_probabilities():
    from backoffice.validation import account_settings
    body = {"strategy": 5, "stake": "high", "frequency": "low", "max_minutes": 240, "max_tables": 4,
            "post_bb_chance": .1, "run_it_twice_chance": .9, "rebuy_ring_chance": .85,
            "rebuy_tournament_chance": .4, "buy_in_weights": {"100": 100}}
    values = account_settings(body)
    assert (float(values["rebuy_ring_chance"]), float(values["rebuy_tournament_chance"])) == (.85, .4)
    for field, value in (("rebuy_ring_chance", 1.2), ("rebuy_tournament_chance", None)):
        with pytest.raises(Error):
            account_settings({**body, field: value})


def test_task_and_session_ranges_use_site_wall_clock():
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from backoffice.store import local_range
    zone, now = ZoneInfo("Europe/Budapest"), datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)
    start, stop = local_range({}, zone, now)
    assert start == datetime(2026, 10, 31, 23, 0) and stop > now.replace(tzinfo=None)  # 00:00 CET; open-ended To
    start, stop = local_range({"from": "2026-11-01T08:00", "to": "2026-11-01T10:15"}, zone, now)
    assert (start, stop) == (datetime(2026, 11, 1, 7, 0), datetime(2026, 11, 1, 9, 16))
    assert local_range({"from": "2026-10-30", "to": "2026-10-31"}, zone, now)[1] == datetime(2026, 10, 31, 23, 0)
    for bad in ({"from": "yesterday"}, {"from": "2026-11-01T10:00", "to": "2026-11-01T09:00"}):
        with pytest.raises(Error):
            local_range(bad, zone, now)
