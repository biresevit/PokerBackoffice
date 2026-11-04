-- Move shared casino settings to one row per customer and enabled poker site.
-- Preserve the previous values for every customer already registered at that casino.
IF COL_LENGTH('dbo.CasinoSettings','CustomerId') IS NULL
BEGIN
    IF OBJECT_ID('dbo.CasinoSettingsLegacy','U') IS NULL
        SELECT * INTO dbo.CasinoSettingsLegacy FROM dbo.CasinoSettings;
    ALTER TABLE dbo.CasinoSettings ADD CustomerId int NULL;
END;
GO
DECLARE @enabled TABLE(CustomerId int,Casino nvarchar(50),PRIMARY KEY(CustomerId,Casino));
INSERT @enabled SELECT CustomerId,Casino FROM scheduler.Site
    UNION SELECT CustomerId,Casino FROM dbo.CustomerMachine WHERE IsActive=1;
UPDATE s SET CustomerId=(SELECT MIN(e.CustomerId) FROM @enabled e WHERE e.Casino=s.Casino)
    FROM dbo.CasinoSettings s WHERE CustomerId IS NULL;
-- A shared row with no enabled customer stays in the private legacy archive.
DELETE dbo.CasinoSettings WHERE CustomerId IS NULL;
ALTER TABLE dbo.CasinoSettings DROP CONSTRAINT PK_CasinoSettings;
ALTER TABLE dbo.CasinoSettings ALTER COLUMN CustomerId int NOT NULL;
ALTER TABLE dbo.CasinoSettings ADD CONSTRAINT PK_CasinoSettings PRIMARY KEY(CustomerId,Casino);
ALTER TABLE dbo.CasinoSettings ADD CONSTRAINT FK_CasinoSettings_Customer FOREIGN KEY(CustomerId) REFERENCES dbo.Customer(CustomerId);
INSERT dbo.CasinoSettings(CustomerId,Casino,UseHelp,ProfileVsHumans,ProfileMaxStake,ProfileInTournaments)
    SELECT e.CustomerId,e.Casino,COALESCE(l.UseHelp,0),COALESCE(l.ProfileVsHumans,'Everyone'),l.ProfileMaxStake,COALESCE(l.ProfileInTournaments,1)
    FROM @enabled e LEFT JOIN dbo.CasinoSettingsLegacy l ON l.Casino=e.Casino
    WHERE NOT EXISTS(SELECT 1 FROM dbo.CasinoSettings s WHERE s.CustomerId=e.CustomerId AND s.Casino=e.Casino);
GO
CREATE OR ALTER PROCEDURE dbo.CasinoSettings_Initialize
    @CustomerId int,@Casino nvarchar(50)
AS
BEGIN
    SET NOCOUNT ON;
    INSERT dbo.CasinoSettings(CustomerId,Casino)
        SELECT @CustomerId,@Casino WHERE NOT EXISTS(
            SELECT 1 FROM dbo.CasinoSettings WITH(UPDLOCK,HOLDLOCK) WHERE CustomerId=@CustomerId AND Casino=@Casino);
END;
GO
CREATE OR ALTER TRIGGER dbo.CustomerMachine_InitializeCasinoSettings ON dbo.CustomerMachine AFTER INSERT,UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    INSERT dbo.CasinoSettings(CustomerId,Casino)
        SELECT DISTINCT i.CustomerId,i.Casino FROM inserted i WHERE i.IsActive=1 AND NOT EXISTS(
            SELECT 1 FROM dbo.CasinoSettings s WITH(UPDLOCK,HOLDLOCK) WHERE s.CustomerId=i.CustomerId AND s.Casino=i.Casino);
END;
GO
CREATE OR ALTER TRIGGER scheduler.Site_InitializeCasinoSettings ON scheduler.Site AFTER INSERT,UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    -- SchedulingEnabled pauses traffic; the customer's configured site and its settings remain enabled.
    INSERT dbo.CasinoSettings(CustomerId,Casino)
        SELECT DISTINCT i.CustomerId,i.Casino FROM inserted i WHERE NOT EXISTS(
            SELECT 1 FROM dbo.CasinoSettings s WITH(UPDLOCK,HOLDLOCK) WHERE s.CustomerId=i.CustomerId AND s.Casino=i.Casino);
END;
GO
CREATE OR ALTER PROCEDURE dbo.CasinoSettings_List
    @CustomerId int=NULL,@Casino nvarchar(50)=NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @CustomerId IS NULL
    BEGIN
        -- Legacy clients have no customer context. Return fixed defaults, never any customer's configured values.
        SELECT DISTINCT Casino,CAST(0 AS bit) AS UseHelp,CAST('Everyone' AS varchar(20)) AS ProfileVsHumans,
            CAST(NULL AS varchar(10)) AS ProfileMaxStake,CAST(1 AS bit) AS ProfileInTournaments FROM dbo.CasinoSettings;
        RETURN;
    END;
    SELECT Casino,UseHelp,ProfileVsHumans,ProfileMaxStake,ProfileInTournaments FROM dbo.CasinoSettings
        WHERE CustomerId=@CustomerId AND (@Casino IS NULL OR Casino=@Casino);
END;
GO
CREATE OR ALTER PROCEDURE dbo.CasinoSettings_Upsert
    @Casino nvarchar(50),@UseHelp bit=0,@ProfileVsHumans varchar(20)='Everyone',
    @ProfileMaxStake varchar(10)=NULL,@ProfileInTournaments bit=1,@CustomerId int=NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @CustomerId IS NULL THROW 51120,'CustomerId is required for casino settings.',1;
    UPDATE dbo.CasinoSettings WITH(UPDLOCK,HOLDLOCK)
        SET UseHelp=@UseHelp,ProfileVsHumans=@ProfileVsHumans,ProfileMaxStake=@ProfileMaxStake,
            ProfileInTournaments=@ProfileInTournaments,UpdatedUtc=SYSUTCDATETIME()
        WHERE CustomerId=@CustomerId AND Casino=@Casino;
    IF @@ROWCOUNT=0 INSERT dbo.CasinoSettings(CustomerId,Casino,UseHelp,ProfileVsHumans,ProfileMaxStake,ProfileInTournaments)
        VALUES(@CustomerId,@Casino,@UseHelp,@ProfileVsHumans,@ProfileMaxStake,@ProfileInTournaments);
END;
GO
GRANT EXECUTE ON dbo.CasinoSettings_List TO pdecision_client;
