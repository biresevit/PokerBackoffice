IF SCHEMA_ID(N'backoffice') IS NULL EXEC(N'CREATE SCHEMA backoffice');
GO
CREATE TABLE backoffice.Membership (
    Provider varchar(20) NOT NULL,
    Subject nvarchar(200) NOT NULL,
    CustomerId int NOT NULL REFERENCES dbo.Customer(CustomerId),
    DisplayEmail nvarchar(254) NULL,
    Role varchar(10) NOT NULL CHECK(Role IN ('viewer','operator')),
    IsActive bit NOT NULL DEFAULT 1,
    CreatedUtc datetime2(3) NOT NULL DEFAULT SYSUTCDATETIME(),
    PRIMARY KEY(Provider,Subject,CustomerId)
);
CREATE TABLE backoffice.AccessRequest (
    Provider varchar(20) NOT NULL,
    Subject nvarchar(200) NOT NULL,
    UserDetails nvarchar(254) NOT NULL,
    RequestedUtc datetime2(3) NOT NULL DEFAULT SYSUTCDATETIME(),
    PRIMARY KEY(Provider,Subject)
);
CREATE TABLE backoffice.AuditLog (
    Id bigint IDENTITY PRIMARY KEY,
    CustomerId int NOT NULL REFERENCES dbo.Customer(CustomerId),
    Provider varchar(20) NOT NULL,
    Subject nvarchar(200) NOT NULL,
    Action varchar(50) NOT NULL,
    Entity nvarchar(100) NOT NULL,
    DetailJson nvarchar(max) NOT NULL CHECK(ISJSON(DetailJson)=1),
    CreatedUtc datetime2(3) NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX IX_BackofficeAudit_Customer ON backoffice.AuditLog(CustomerId,CreatedUtc);
CREATE TABLE backoffice.MachineMetadata (
    MachineId int NOT NULL PRIMARY KEY REFERENCES dbo.CustomerMachine(MachineId),
    HostName nvarchar(200) NULL,
    PublicIp varchar(45) NULL,
    PrivateIp varchar(45) NULL,
    LastAgentUtc datetime2(3) NULL,
    Version bigint NOT NULL DEFAULT 1
);
CREATE TABLE backoffice.MachineAllowedSite (
    MachineId int NOT NULL REFERENCES dbo.CustomerMachine(MachineId),
    SiteId int NOT NULL REFERENCES scheduler.Site(SiteId),
    PRIMARY KEY(MachineId,SiteId)
);
ALTER TABLE scheduler.AccountPolicy ADD DeletedUtc datetime2(3) NULL;
INSERT backoffice.MachineMetadata(MachineId) SELECT MachineId FROM dbo.CustomerMachine;
INSERT backoffice.MachineAllowedSite(MachineId,SiteId) SELECT MachineId,SiteId FROM scheduler.MachineAssignment;
GO
CREATE TRIGGER backoffice.MachineAllowedSite_CheckScope ON backoffice.MachineAllowedSite AFTER INSERT,UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS(SELECT 1 FROM inserted i JOIN dbo.CustomerMachine m ON m.MachineId=i.MachineId
              JOIN scheduler.Site s ON s.SiteId=i.SiteId WHERE s.CustomerId<>m.CustomerId)
        THROW 51101,'Machine and allowed site must belong to the same customer',1;
END;
