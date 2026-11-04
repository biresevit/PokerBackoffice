-- Stores only hashed rate-limit buckets and attempt counts, never enquiry contents.
IF OBJECT_ID('backoffice.ContactRateLimit','U') IS NULL
BEGIN
    CREATE TABLE backoffice.ContactRateLimit(
        Bucket char(64) NOT NULL,
        WindowStart datetime2 NOT NULL,
        Attempts int NOT NULL,
        CONSTRAINT PK_ContactRateLimit PRIMARY KEY(Bucket,WindowStart)
    );
END;
IF DATABASE_PRINCIPAL_ID('poker_backoffice_app') IS NOT NULL
    GRANT SELECT,INSERT,UPDATE,DELETE ON OBJECT::backoffice.ContactRateLimit TO poker_backoffice_app;
