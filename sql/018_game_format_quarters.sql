-- Game formats of new accounts, as the default and on every site: a quarter each for all formats, NLH only,
-- PLO4 and PLO5 only, and MTT/SNG only (ScheduleController migration 035). Existing accounts keep their formats
-- until the distribution is applied on the Accounts page.
DECLARE @games nvarchar(max) = N'[{"value": "NLH,PLO4,PLO5", "percent": "25"}, {"value": "NLH", "percent": "25"}, {"value": "PLO4,PLO5", "percent": "25"}, {"value": "TOURNAMENTS", "percent": "25"}]';
UPDATE backoffice.DefaultAccountDistribution SET OptionsJson=@games WHERE Field='games';
INSERT backoffice.DefaultAccountDistribution(Field,OptionsJson)
    SELECT 'games',@games WHERE NOT EXISTS(SELECT 1 FROM backoffice.DefaultAccountDistribution WHERE Field='games');
UPDATE backoffice.AccountDistribution SET OptionsJson=@games,UpdatedUtc=SYSUTCDATETIME() WHERE Field='games';
INSERT backoffice.AccountDistribution(SiteId,Field,OptionsJson)
    SELECT s.SiteId,'games',@games FROM scheduler.Site s
    WHERE NOT EXISTS(SELECT 1 FROM backoffice.AccountDistribution a WHERE a.SiteId=s.SiteId AND a.Field='games');
