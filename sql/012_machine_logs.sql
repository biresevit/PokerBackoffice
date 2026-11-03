CREATE TABLE backoffice.MachineLogRequest(
 RequestId uniqueidentifier NOT NULL PRIMARY KEY,
 CustomerId int NOT NULL REFERENCES dbo.Customer(CustomerId),SiteId int NOT NULL REFERENCES scheduler.Site(SiteId),
 MachineId int NOT NULL REFERENCES dbo.CustomerMachine(MachineId),RequestedBy nvarchar(200) NOT NULL,
 Hours int NOT NULL CHECK(Hours BETWEEN 1 AND 168),Status varchar(16) NOT NULL DEFAULT 'queued'
   CHECK(Status IN ('queued','collecting','uploading','ready','failed','expired')),
 CreatedUtc datetime2(3) NOT NULL DEFAULT SYSUTCDATETIME(),UpdatedUtc datetime2(3) NOT NULL DEFAULT SYSUTCDATETIME(),
 ExpiresUtc datetime2(3) NOT NULL,ClaimToken uniqueidentifier NULL,ClaimUntilUtc datetime2(3) NULL,
 BlobName nvarchar(250) NOT NULL,SizeBytes bigint NULL,Sha256 char(64) NULL,Detail nvarchar(1000) NULL);
CREATE INDEX IX_MachineLogs_Poll ON backoffice.MachineLogRequest(MachineId,Status,CreatedUtc);
ALTER TABLE scheduler.MachineUpdateAgent ADD LogCollectorVersion varchar(30) NULL,LogCollectorHeartbeatUtc datetime2(3) NULL;
GO
GRANT SELECT,INSERT,UPDATE ON backoffice.MachineLogRequest TO poker_backoffice_app;
