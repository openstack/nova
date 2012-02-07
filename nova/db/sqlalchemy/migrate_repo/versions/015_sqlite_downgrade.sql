BEGIN TRANSACTION;
    CREATE TEMPORARY TABLE floating_ips_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        address VARCHAR(255),
        fixed_ip_id INTEGER,
        project_id VARCHAR(255),
        host VARCHAR(255),
        auto_assigned BOOLEAN,
        PRIMARY KEY (id),
        CHECK (deleted IN (0, 1)),
        CHECK (auto_assigned IN (0, 1)),
        FOREIGN KEY(fixed_ip_id) REFERENCES fixed_ips (id)
    );

    INSERT INTO floating_ips_backup
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               address,
               fixed_ip_id,
               project_id,
               host,
               auto_assigned
        FROM floating_ips;

    DROP TABLE floating_ips;

    CREATE TABLE floating_ips (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        address VARCHAR(255),
        fixed_ip_id INTEGER,
        project_id VARCHAR(255),
        host VARCHAR(255),
        PRIMARY KEY (id),
        CHECK (deleted IN (0, 1)),
        FOREIGN KEY(fixed_ip_id) REFERENCES fixed_ips (id)
    );

    INSERT INTO floating_ips
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               address,
               fixed_ip_id,
               project_id,
               host
        FROM floating_ips_backup;

    DROP TABLE floating_ips_backup;
COMMIT;
