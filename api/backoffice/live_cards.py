"""Short-lived, customer-scoped bot views for optional live card sharing."""
import json
from datetime import datetime, timezone


def merge_cards(payload, snapshots):
    """Only reveal a source bot's own cards in the exact same table and hand."""
    shared = 0
    if not payload.get('hand_id'):
        return shared
    for row in snapshots:
        source = json.loads(row['payload']) if row.get('payload') else {}
        if (str(source.get('table_id')) != str(payload.get('table_id'))
                or str(source.get('hand_id')) != str(payload['hand_id'])
                or source.get('board') != payload.get('board')
                or source.get('game') != payload.get('game')
                or source.get('hero', '').casefold() != row['username'].casefold()):
            continue
        heroes = [s for s in source.get('seats', []) if s.get('hero')]
        if len(heroes) != 1:
            continue
        hero = heroes[0]
        cards = hero.get('cards', [])
        expected = {'NLH': 2, 'PLO4': 4, 'PLO5': 5}.get(payload.get('game'))
        if (not expected or len(cards) != expected or len(set(cards)) != expected
                or any(not isinstance(c, str) or len(c) != 2
                       or c[0] not in '23456789tjqkaTJQKA' or c[1] not in 'cdhs' for c in cards)):
            continue
        for seat in payload.get('seats', []):
            if (not seat.get('hero') and not seat.get('cards') and seat.get('in_game')
                    and seat.get('seat') == hero.get('seat')
                    and seat.get('name') == hero.get('name')):
                seat.update(cards=cards, shared_cards=True)
                shared += 1
    return shared


def enrich(store, site_id, row):
    payload = row.get('payload')
    if not payload:
        return
    from .casino_settings import CasinoSettings
    settings = CasinoSettings(store).row(store.site(site_id)['name'])
    enabled = bool(settings and settings['use_help'])
    payload['card_sharing'] = {'enabled': enabled, 'shared_bots': 0}
    if not enabled or row['status'] != 'active':
        return
    # Every bot publishes only its own perspective. These leases expire when
    # the browser closes or the setting is switched off; no PC update needed.
    created = store.db.rows('''DECLARE @expires datetime2=DATEADD(second,45,SYSUTCDATETIME());
        UPDATE r SET ExpiresUtc=@expires FROM scheduler.LiveViewRequest r
        JOIN scheduler.Site c ON c.SiteId=r.SiteId
        WHERE r.SiteId=%s AND r.TableId=%s AND r.RequestedBy=%s AND c.CustomerId=%s
          AND r.Status IN ('requested','active') AND r.ExpiresUtc>SYSUTCDATETIME()
          AND r.ExpiresUtc<DATEADD(second,30,SYSUTCDATETIME());
        INSERT scheduler.LiveViewRequest(RequestId,SiteId,TableId,BotAccountId,MachineId,
            RequestedBy,ExpiresUtc,Status)
        OUTPUT inserted.RequestId AS request_id,inserted.BotAccountId AS account_id
        SELECT NEWID(),e.SiteId,e.TableId,e.BotAccountId,e.MachineId,%s,@expires,'requested'
        FROM scheduler.Entry e JOIN scheduler.Site c ON c.SiteId=e.SiteId
        WHERE e.SiteId=%s AND e.TableId=%s AND e.IsOpen=1 AND c.CustomerId=%s
          AND e.Status IN ('seated','sitting_out','draining')
          AND NOT EXISTS(SELECT 1 FROM scheduler.LiveViewRequest r WITH(UPDLOCK,HOLDLOCK)
              WHERE r.SiteId=e.SiteId AND r.TableId=e.TableId AND r.BotAccountId=e.BotAccountId
                AND r.MachineId=e.MachineId AND r.RequestedBy=%s
                AND r.Status IN ('requested','active') AND r.ExpiresUtc>SYSUTCDATETIME())
        GROUP BY e.SiteId,e.TableId,e.BotAccountId,e.MachineId''',
        site_id,row['table_id'],store.ctx.subject,store.ctx.customer_id,store.ctx.subject,
        site_id,row['table_id'],store.ctx.customer_id,store.ctx.subject)
    if created:
        store.audit('tables.live.cards.request',site_id,{'requests':created})
    snapshots = store.db.rows('''SELECT s.PayloadJson AS payload,b.Username AS username
        FROM scheduler.LiveViewRequest r JOIN scheduler.LiveTableSnapshot s ON s.RequestId=r.RequestId
        JOIN dbo.BotAccount b ON b.BotAccountId=r.BotAccountId
        JOIN scheduler.Site c ON c.SiteId=r.SiteId
        WHERE r.SiteId=%s AND r.TableId=%s AND r.RequestedBy=%s AND c.CustomerId=%s
          AND r.Status='active' AND r.ExpiresUtc>SYSUTCDATETIME()
          AND s.CapturedUtc>=DATEADD(second,-10,SYSUTCDATETIME())
        ORDER BY s.CapturedUtc DESC''', site_id, row['table_id'], store.ctx.subject, store.ctx.customer_id)
    # A frozen target snapshot must never borrow cards from a current source.
    captured = row.get('captured')
    if captured and (datetime.now(timezone.utc) - captured.replace(tzinfo=timezone.utc)).total_seconds() <= 10:
        payload['card_sharing']['shared_bots'] = merge_cards(payload, snapshots)
