-- Conditions for card sharing and account profiles against humans: a minimum big blind for each feature and an
-- optional customer-managed player list per feature ('ListedPlayers' = only in hands with one of those players).
-- Columns are added with defaults, so PDecision builds that do not know them keep their current behaviour.
IF COL_LENGTH('dbo.CasinoSettings','HelpMinBigBlind') IS NULL
    ALTER TABLE dbo.CasinoSettings ADD HelpMinBigBlind decimal(18,4) NULL
        CONSTRAINT CK_CasinoSettings_HelpMinBigBlind CHECK(HelpMinBigBlind>=0);
IF COL_LENGTH('dbo.CasinoSettings','HelpVsHumans') IS NULL
    ALTER TABLE dbo.CasinoSettings ADD HelpVsHumans varchar(20) NOT NULL
        CONSTRAINT DF_CasinoSettings_HelpVsHumans DEFAULT('Everyone')
        CONSTRAINT CK_CasinoSettings_HelpVsHumans CHECK(HelpVsHumans IN ('Everyone','ListedPlayers'));
IF COL_LENGTH('dbo.CasinoSettings','ProfileMinBigBlind') IS NULL
    ALTER TABLE dbo.CasinoSettings ADD ProfileMinBigBlind decimal(18,4) NULL
        CONSTRAINT CK_CasinoSettings_ProfileMinBigBlind CHECK(ProfileMinBigBlind>=0);
GO
-- Allow 'ListedPlayers' for ProfileVsHumans. The old check may carry a generated name, so drop whatever is there.
DECLARE @name sysname,@sql nvarchar(400);
SELECT @name=cc.name FROM sys.check_constraints cc
    JOIN sys.columns c ON c.object_id=cc.parent_object_id AND c.column_id=cc.parent_column_id
    WHERE cc.parent_object_id=OBJECT_ID('dbo.CasinoSettings') AND c.name='ProfileVsHumans';
IF @name IS NOT NULL
BEGIN
    SET @sql=N'ALTER TABLE dbo.CasinoSettings DROP CONSTRAINT '+QUOTENAME(@name);
    EXEC(@sql);
END;
ALTER TABLE dbo.CasinoSettings ADD CONSTRAINT CK_CasinoSettings_ProfileVsHumans
    CHECK(ProfileVsHumans IN ('Everyone','WeakHumans','ListedPlayers','Never'));
GO
IF OBJECT_ID('dbo.CasinoSettingsPlayer','U') IS NULL
    CREATE TABLE dbo.CasinoSettingsPlayer(
        CustomerId int NOT NULL,
        Casino nvarchar(50) NOT NULL,
        Feature varchar(20) NOT NULL CONSTRAINT CK_CasinoSettingsPlayer_Feature CHECK(Feature IN ('CardSharing','Profile')),
        PlayerName nvarchar(100) NOT NULL,
        AddedUtc datetime2(0) NOT NULL CONSTRAINT DF_CasinoSettingsPlayer_AddedUtc DEFAULT(SYSUTCDATETIME()),
        CONSTRAINT PK_CasinoSettingsPlayer PRIMARY KEY(CustomerId,Casino,Feature,PlayerName),
        CONSTRAINT FK_CasinoSettingsPlayer_Settings FOREIGN KEY(CustomerId,Casino) REFERENCES dbo.CasinoSettings(CustomerId,Casino));
GO
CREATE OR ALTER PROCEDURE dbo.CasinoSettings_List
    @CustomerId int=NULL,@Casino nvarchar(50)=NULL
AS
BEGIN
    SET NOCOUNT ON;
    -- New columns come after the original five: PDecision builds before 1.0.0.49 read only the first five.
    IF @CustomerId IS NULL
    BEGIN
        -- Legacy clients have no customer context. Return fixed defaults, never any customer's configured values.
        SELECT DISTINCT Casino,CAST(0 AS bit) AS UseHelp,CAST('Everyone' AS varchar(20)) AS ProfileVsHumans,
            CAST(NULL AS varchar(10)) AS ProfileMaxStake,CAST(1 AS bit) AS ProfileInTournaments,
            CAST(NULL AS decimal(18,4)) AS HelpMinBigBlind,CAST('Everyone' AS varchar(20)) AS HelpVsHumans,
            CAST(NULL AS decimal(18,4)) AS ProfileMinBigBlind FROM dbo.CasinoSettings;
        RETURN;
    END;
    SELECT Casino,UseHelp,ProfileVsHumans,ProfileMaxStake,ProfileInTournaments,HelpMinBigBlind,HelpVsHumans,ProfileMinBigBlind
        FROM dbo.CasinoSettings WHERE CustomerId=@CustomerId AND (@Casino IS NULL OR Casino=@Casino);
END;
GO
CREATE OR ALTER PROCEDURE dbo.CasinoSettingsPlayer_List
    @CustomerId int,@Casino nvarchar(50)=NULL
AS
BEGIN
    SET NOCOUNT ON;
    SELECT Casino,Feature,PlayerName FROM dbo.CasinoSettingsPlayer
        WHERE CustomerId=@CustomerId AND (@Casino IS NULL OR Casino=@Casino);
END;
GO
CREATE OR ALTER PROCEDURE dbo.CasinoSettings_Upsert
    @Casino nvarchar(50),@UseHelp bit=0,@ProfileVsHumans varchar(20)='Everyone',
    @ProfileMaxStake varchar(10)=NULL,@ProfileInTournaments bit=1,@CustomerId int=NULL,
    @HelpMinBigBlind decimal(18,4)=NULL,@HelpVsHumans varchar(20)='Everyone',@ProfileMinBigBlind decimal(18,4)=NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @CustomerId IS NULL THROW 51120,'CustomerId is required for casino settings.',1;
    UPDATE dbo.CasinoSettings WITH(UPDLOCK,HOLDLOCK)
        SET UseHelp=@UseHelp,ProfileVsHumans=@ProfileVsHumans,ProfileMaxStake=@ProfileMaxStake,
            ProfileInTournaments=@ProfileInTournaments,HelpMinBigBlind=@HelpMinBigBlind,HelpVsHumans=@HelpVsHumans,
            ProfileMinBigBlind=@ProfileMinBigBlind,UpdatedUtc=SYSUTCDATETIME()
        WHERE CustomerId=@CustomerId AND Casino=@Casino;
    IF @@ROWCOUNT=0 INSERT dbo.CasinoSettings(CustomerId,Casino,UseHelp,ProfileVsHumans,ProfileMaxStake,ProfileInTournaments,
            HelpMinBigBlind,HelpVsHumans,ProfileMinBigBlind)
        VALUES(@CustomerId,@Casino,@UseHelp,@ProfileVsHumans,@ProfileMaxStake,@ProfileInTournaments,
            @HelpMinBigBlind,@HelpVsHumans,@ProfileMinBigBlind);
END;
GO
GRANT SELECT,INSERT,DELETE ON OBJECT::dbo.CasinoSettingsPlayer TO poker_backoffice_app;
IF EXISTS(SELECT 1 FROM sys.database_principals WHERE name='pdecision_client')
    GRANT EXECUTE ON dbo.CasinoSettingsPlayer_List TO pdecision_client;
