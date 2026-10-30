CREATE TABLE backoffice.SetupAdministrator(Provider varchar(20) NOT NULL,Subject nvarchar(200) NOT NULL,PRIMARY KEY(Provider,Subject));
CREATE TABLE backoffice.SetupProfile(SiteId int PRIMARY KEY REFERENCES scheduler.Site(SiteId),EncryptedProfile nvarchar(max) NOT NULL,UpdatedUtc datetime2 NOT NULL DEFAULT SYSUTCDATETIME());
CREATE TABLE backoffice.DevicePairing(RequestId uniqueidentifier PRIMARY KEY,Code varchar(12) NOT NULL UNIQUE,HostName nvarchar(200) NOT NULL,MacsJson nvarchar(600) NOT NULL,PublicKey nvarchar(2000) NOT NULL,SourceHash char(64) NOT NULL,CreatedUtc datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),ExpiresUtc datetime2 NOT NULL,Status varchar(12) NOT NULL DEFAULT 'pending' CHECK(Status IN ('pending','approved','completed')),CustomerId int NULL,SiteId int NULL,MachineId int NULL,EnvelopeJson nvarchar(max) NULL,LastNonce varchar(64) NULL);
CREATE INDEX IX_DevicePairing_Source ON backoffice.DevicePairing(SourceHash,CreatedUtc);
GRANT SELECT ON backoffice.SetupAdministrator TO poker_backoffice_app;
GRANT SELECT ON backoffice.SetupProfile TO poker_backoffice_app;
GRANT SELECT,INSERT,UPDATE,DELETE ON backoffice.DevicePairing TO poker_backoffice_app;
GO
CREATE OR ALTER PROCEDURE backoffice.RegisterPairedMachine
 @CustomerId int,@SiteId int,@Mac char(17),@Host nvarchar(200),@Capacity int
AS
BEGIN
 SET NOCOUNT ON;SET XACT_ABORT ON;
 IF NOT EXISTS(SELECT 1 FROM scheduler.Site s JOIN dbo.Customer c ON c.CustomerId=s.CustomerId WHERE s.SiteId=@SiteId AND c.CustomerId=@CustomerId AND c.IsActive=1)
  THROW 51130,'Invalid customer/site',1;
 DECLARE @mid int=(SELECT MachineId FROM dbo.CustomerMachine WITH(UPDLOCK,HOLDLOCK) WHERE MacAddress=@Mac);
 IF @mid IS NOT NULL AND NOT EXISTS(SELECT 1 FROM dbo.CustomerMachine WHERE MachineId=@mid AND CustomerId=@CustomerId AND IsActive=1)
  THROW 51131,'Machine belongs to another customer or is inactive',1;
 IF @mid IS NULL BEGIN
  INSERT dbo.CustomerMachine(CustomerId,MacAddress,Casino,Platform,Description) SELECT @CustomerId,@Mac,Casino,Platform,@Host FROM scheduler.Site WHERE SiteId=@SiteId;
  SET @mid=SCOPE_IDENTITY();
 END;
 IF EXISTS(SELECT 1 FROM scheduler.MachineAssignment WHERE MachineId=@mid AND SiteId<>@SiteId) THROW 51132,'Machine assigned to another site',1;
 IF NOT EXISTS(SELECT 1 FROM scheduler.MachineAssignment WHERE MachineId=@mid) INSERT scheduler.MachineAssignment(MachineId,SiteId,MaxEntries,IsEnabled) VALUES(@mid,@SiteId,@Capacity,1);
 IF NOT EXISTS(SELECT 1 FROM backoffice.MachineMetadata WHERE MachineId=@mid) INSERT backoffice.MachineMetadata(MachineId,HostName) VALUES(@mid,@Host);
 IF NOT EXISTS(SELECT 1 FROM backoffice.MachineAllowedSite WHERE MachineId=@mid AND SiteId=@SiteId) INSERT backoffice.MachineAllowedSite(MachineId,SiteId) VALUES(@mid,@SiteId);
 SELECT @mid AS MachineId;
END;
GO
GRANT EXECUTE ON backoffice.RegisterPairedMachine TO poker_backoffice_app;
