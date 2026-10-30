-- Administrator template. Replace MAC/hostname; review customer/site.
SET XACT_ABORT ON;
BEGIN TRANSACTION;
DECLARE @customer nvarchar(100)=N'Nenad', @site int=1;
DECLARE @mac varchar(17)='AA-BB-CC-DD-EE-FF'; -- REPLACE
DECLARE @host nvarchar(200)=N'NEW-PC'; -- REPLACE
DECLARE @cid int=(SELECT CustomerId FROM dbo.Customer
                 WHERE CustomerName=@customer AND IsActive=1);
IF @cid IS NULL OR NOT EXISTS(SELECT 1 FROM scheduler.Site
    WHERE SiteId=@site AND CustomerId=@cid)
    THROW 51120,'Customer/site mismatch',1;
IF @mac='AA-BB-CC-DD-EE-FF' OR @host=N'NEW-PC'
    THROW 51121,'Replace example MAC and hostname',1;
IF EXISTS(SELECT 1 FROM dbo.CustomerMachine WHERE MacAddress=@mac)
    THROW 51122,'Machine already registered; review existing record',1;
EXEC dbo.Machine_Upsert @CustomerName=@customer,@MacAddress=@mac,
    @Casino=N'Evenbet',@Platform=N'EvenBet',@Description=@host;
DECLARE @mid int=(SELECT MachineId FROM dbo.CustomerMachine
                 WHERE MacAddress=@mac AND CustomerId=@cid);
IF @mid IS NULL THROW 51123,'Machine registration failed',1;
INSERT scheduler.MachineAssignment
    (MachineId,SiteId,MaxEntries,IsEnabled)
    VALUES(@mid,@site,30,1);
INSERT backoffice.MachineMetadata(MachineId,HostName)
    VALUES(@mid,@host);
INSERT backoffice.MachineAllowedSite(MachineId,SiteId)
    VALUES(@mid,@site);
COMMIT;
SELECT @mid AS NewMachineId;
