-- Value distributions for account settings, per site: e.g. the profile mix (15 percent Strong Balanced, ...).
-- OptionsJson is [{"value": ..., "percent": "15.00"}, ...] with percentages totalling 100.
-- (No percent signs in this file: the migration runner passes it through a driver that formats them.)
IF OBJECT_ID(N'backoffice.AccountDistribution', N'U') IS NULL
CREATE TABLE backoffice.AccountDistribution(
    SiteId int NOT NULL CONSTRAINT FK_AccountDistribution_Site REFERENCES scheduler.Site(SiteId),
    Field varchar(40) NOT NULL,
    OptionsJson nvarchar(max) NOT NULL CONSTRAINT CK_AccountDistribution_Json CHECK(ISJSON(OptionsJson)=1),
    UpdatedUtc datetime2(3) NOT NULL CONSTRAINT DF_AccountDistribution_Updated DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_AccountDistribution PRIMARY KEY(SiteId, Field)
);
GO
GRANT SELECT, INSERT, UPDATE, DELETE ON backoffice.AccountDistribution TO poker_backoffice_app;
