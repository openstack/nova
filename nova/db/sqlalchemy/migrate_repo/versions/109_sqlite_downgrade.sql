BEGIN TRANSACTION;
    CREATE TEMPORARY TABLE dns_domains_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        domain VARCHAR(512) NOT NULL,
        scope VARCHAR(255),
        availability_zone VARCHAR(255),
        project_id VARCHAR(255),
        PRIMARY KEY (domain)
    );

    INSERT INTO dns_domains_backup 
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               domain,
               scope,
               availability_zone,
               project_id
        FROM dns_domains;

    DROP TABLE dns_domains;

    CREATE TABLE dns_domains (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        domain VARCHAR(512) NOT NULL,
        scope VARCHAR(255),
        availability_zone VARCHAR(255),
        project_id VARCHAR(255),
        PRIMARY KEY (domain),
        FOREIGN KEY (project_id) REFERENCES projects (id)
    );

    INSERT INTO dns_domains 
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               domain,
               scope,
               availability_zone,
               project_id
        FROM dns_domains_backup;

    DROP TABLE dns_domains_backup;

COMMIT;
