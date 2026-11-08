-- Default distributions for the account settings added by ScheduleController migration 033:
-- game formats 33 all formats / 33 NLH only / 34 PLO4 and PLO5 only, and for each of the four tournament limits
-- (SNG/MTT rebuys, SNG/MTT re-entries) 33 none / 33 one / 34 two. New sites copy the defaults through
-- scheduler.Site_InitializeAccountDistributions; existing sites get them where they have none for the setting.
DECLARE @defaults TABLE(Field varchar(40) PRIMARY KEY, OptionsJson nvarchar(max) NOT NULL);
INSERT @defaults(Field,OptionsJson) VALUES
 ('games','[{"value": "NLH,PLO4,PLO5", "percent": "33"}, {"value": "NLH", "percent": "33"}, {"value": "PLO4,PLO5", "percent": "34"}]'),
 ('max_sng_rebuys','[{"value": 0, "percent": "33"}, {"value": 1, "percent": "33"}, {"value": 2, "percent": "34"}]'),
 ('max_mtt_rebuys','[{"value": 0, "percent": "33"}, {"value": 1, "percent": "33"}, {"value": 2, "percent": "34"}]'),
 ('max_sng_reentries','[{"value": 0, "percent": "33"}, {"value": 1, "percent": "33"}, {"value": 2, "percent": "34"}]'),
 ('max_mtt_reentries','[{"value": 0, "percent": "33"}, {"value": 1, "percent": "33"}, {"value": 2, "percent": "34"}]');
INSERT backoffice.DefaultAccountDistribution(Field,OptionsJson)
    SELECT d.Field,d.OptionsJson FROM @defaults d
    WHERE NOT EXISTS(SELECT 1 FROM backoffice.DefaultAccountDistribution x WHERE x.Field=d.Field);
INSERT backoffice.AccountDistribution(SiteId,Field,OptionsJson)
    SELECT s.SiteId,d.Field,d.OptionsJson FROM scheduler.Site s CROSS JOIN @defaults d
    WHERE NOT EXISTS(SELECT 1 FROM backoffice.AccountDistribution a WHERE a.SiteId=s.SiteId AND a.Field=d.Field);
