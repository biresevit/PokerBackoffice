-- Card sharing and "use solver strategy vs humans" are each an on/off switch with the same conditions:
-- a minimum big blind for ring games, a minimum buy-in for SNG/MTT, and a player list. When on, a feature is used
-- at stakes from the minimums up and, whatever the game or stake, in every hand with a listed player.
-- The older columns stay: PDecision builds before 1.0.0.50 read them, and the backoffice keeps writing the closest
-- equivalent there (solver on = profiles 'Never', off = profiles against 'Everyone').
IF COL_LENGTH('dbo.CasinoSettings','HelpMinBuyIn') IS NULL
    ALTER TABLE dbo.CasinoSettings ADD HelpMinBuyIn decimal(18,4) NULL
        CONSTRAINT CK_CasinoSettings_HelpMinBuyIn CHECK(HelpMinBuyIn>=0);
IF COL_LENGTH('dbo.CasinoSettings','SolverVsHumans') IS NULL
    ALTER TABLE dbo.CasinoSettings ADD SolverVsHumans bit NOT NULL
        CONSTRAINT DF_CasinoSettings_SolverVsHumans DEFAULT(0);
IF COL_LENGTH('dbo.CasinoSettings','SolverMinBigBlind') IS NULL
    ALTER TABLE dbo.CasinoSettings ADD SolverMinBigBlind decimal(18,4) NULL
        CONSTRAINT CK_CasinoSettings_SolverMinBigBlind CHECK(SolverMinBigBlind>=0);
IF COL_LENGTH('dbo.CasinoSettings','SolverMinBuyIn') IS NULL
    ALTER TABLE dbo.CasinoSettings ADD SolverMinBuyIn decimal(18,4) NULL
        CONSTRAINT CK_CasinoSettings_SolverMinBuyIn CHECK(SolverMinBuyIn>=0);
GO
-- Profiles 'Never' meant the strong (solver) strategy against every human.
UPDATE dbo.CasinoSettings SET SolverVsHumans=1 WHERE ProfileVsHumans='Never' AND SolverVsHumans=0;
GO
-- The player list of the solver strategy replaces the profile list ('Profile' lists were never used).
DELETE dbo.CasinoSettingsPlayer WHERE Feature='Profile';
ALTER TABLE dbo.CasinoSettingsPlayer DROP CONSTRAINT CK_CasinoSettingsPlayer_Feature;
ALTER TABLE dbo.CasinoSettingsPlayer ADD CONSTRAINT CK_CasinoSettingsPlayer_Feature CHECK(Feature IN ('CardSharing','Solver'));
GO
CREATE OR ALTER PROCEDURE dbo.CasinoSettings_List
    @CustomerId int=NULL,@Casino nvarchar(50)=NULL
AS
BEGIN
    SET NOCOUNT ON;
    -- Columns are only ever appended: PDecision before 1.0.0.49 reads the first five, 1.0.0.49 the first eight.
    IF @CustomerId IS NULL
    BEGIN
        -- Legacy clients have no customer context. Return fixed defaults, never any customer's configured values.
        SELECT DISTINCT Casino,CAST(0 AS bit) AS UseHelp,CAST('Everyone' AS varchar(20)) AS ProfileVsHumans,
            CAST(NULL AS varchar(10)) AS ProfileMaxStake,CAST(1 AS bit) AS ProfileInTournaments,
            CAST(NULL AS decimal(18,4)) AS HelpMinBigBlind,CAST('Everyone' AS varchar(20)) AS HelpVsHumans,
            CAST(NULL AS decimal(18,4)) AS ProfileMinBigBlind,CAST(NULL AS decimal(18,4)) AS HelpMinBuyIn,
            CAST(0 AS bit) AS SolverVsHumans,CAST(NULL AS decimal(18,4)) AS SolverMinBigBlind,
            CAST(NULL AS decimal(18,4)) AS SolverMinBuyIn FROM dbo.CasinoSettings;
        RETURN;
    END;
    SELECT Casino,UseHelp,ProfileVsHumans,ProfileMaxStake,ProfileInTournaments,HelpMinBigBlind,HelpVsHumans,ProfileMinBigBlind,
        HelpMinBuyIn,SolverVsHumans,SolverMinBigBlind,SolverMinBuyIn
        FROM dbo.CasinoSettings WHERE CustomerId=@CustomerId AND (@Casino IS NULL OR Casino=@Casino);
END;
GO
CREATE OR ALTER PROCEDURE dbo.CasinoSettings_Upsert
    @Casino nvarchar(50),@UseHelp bit=0,@CustomerId int=NULL,
    @HelpMinBigBlind decimal(18,4)=NULL,@HelpMinBuyIn decimal(18,4)=NULL,
    @SolverVsHumans bit=0,@SolverMinBigBlind decimal(18,4)=NULL,@SolverMinBuyIn decimal(18,4)=NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @CustomerId IS NULL THROW 51120,'CustomerId is required for casino settings.',1;
    -- legacy columns for PDecision before 1.0.0.50
    DECLARE @Profile varchar(20)=CASE WHEN @SolverVsHumans=1 THEN 'Never' ELSE 'Everyone' END;
    UPDATE dbo.CasinoSettings WITH(UPDLOCK,HOLDLOCK)
        SET UseHelp=@UseHelp,HelpMinBigBlind=@HelpMinBigBlind,HelpVsHumans='Everyone',HelpMinBuyIn=@HelpMinBuyIn,
            SolverVsHumans=@SolverVsHumans,SolverMinBigBlind=@SolverMinBigBlind,SolverMinBuyIn=@SolverMinBuyIn,
            ProfileVsHumans=@Profile,ProfileMaxStake=NULL,ProfileMinBigBlind=NULL,ProfileInTournaments=1-@SolverVsHumans,
            UpdatedUtc=SYSUTCDATETIME()
        WHERE CustomerId=@CustomerId AND Casino=@Casino;
    IF @@ROWCOUNT=0 INSERT dbo.CasinoSettings(CustomerId,Casino,UseHelp,HelpMinBigBlind,HelpVsHumans,HelpMinBuyIn,
            SolverVsHumans,SolverMinBigBlind,SolverMinBuyIn,ProfileVsHumans,ProfileMaxStake,ProfileMinBigBlind,ProfileInTournaments)
        VALUES(@CustomerId,@Casino,@UseHelp,@HelpMinBigBlind,'Everyone',@HelpMinBuyIn,
            @SolverVsHumans,@SolverMinBigBlind,@SolverMinBuyIn,@Profile,NULL,NULL,1-@SolverVsHumans);
END;
