-- Value distributions every new poker site starts with, taken from customer Nenad's EvenBet site.
-- Sites that have no distribution for a setting get the default one too; their own distributions stay.
IF OBJECT_ID(N'backoffice.DefaultAccountDistribution', N'U') IS NULL
CREATE TABLE backoffice.DefaultAccountDistribution(
    Field varchar(40) NOT NULL CONSTRAINT PK_DefaultAccountDistribution PRIMARY KEY,
    OptionsJson nvarchar(max) NOT NULL CONSTRAINT CK_DefaultAccountDistribution_Json CHECK(ISJSON(OptionsJson)=1),
    UpdatedUtc datetime2(3) NOT NULL CONSTRAINT DF_DefaultAccountDistribution_Updated DEFAULT SYSUTCDATETIME()
);
GO
INSERT backoffice.DefaultAccountDistribution(Field,OptionsJson)
    SELECT d.Field,d.OptionsJson FROM backoffice.AccountDistribution d
    JOIN scheduler.Site s ON s.SiteId=d.SiteId JOIN dbo.Customer c ON c.CustomerId=s.CustomerId
    WHERE c.CustomerName=N'Nenad' AND s.Casino=N'Evenbet'
      AND NOT EXISTS(SELECT 1 FROM backoffice.DefaultAccountDistribution x WHERE x.Field=d.Field);
INSERT backoffice.AccountDistribution(SiteId,Field,OptionsJson)
    SELECT s.SiteId,d.Field,d.OptionsJson FROM scheduler.Site s CROSS JOIN backoffice.DefaultAccountDistribution d
    WHERE NOT EXISTS(SELECT 1 FROM backoffice.AccountDistribution a WHERE a.SiteId=s.SiteId AND a.Field=d.Field);
GO
CREATE OR ALTER TRIGGER scheduler.Site_InitializeAccountDistributions ON scheduler.Site AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT backoffice.AccountDistribution(SiteId,Field,OptionsJson)
        SELECT i.SiteId,d.Field,d.OptionsJson FROM inserted i CROSS JOIN backoffice.DefaultAccountDistribution d
        WHERE NOT EXISTS(SELECT 1 FROM backoffice.AccountDistribution a WHERE a.SiteId=i.SiteId AND a.Field=d.Field);
END;
GO
GRANT SELECT ON backoffice.DefaultAccountDistribution TO poker_backoffice_app;
