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
