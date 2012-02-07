BEGIN TRANSACTION;

    CREATE TEMPORARY TABLE fixed_ips_backup (
        id INTEGER NOT NULL,
        address VARCHAR(255),
        network_id INTEGER,
        instance_id INTEGER,
        allocated BOOLEAN DEFAULT FALSE,
        leased BOOLEAN DEFAULT FALSE,
        reserved BOOLEAN DEFAULT FALSE,
        created_at DATETIME NOT NULL,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN NOT NULL,
        addressV6 VARCHAR(255),
        netmaskV6 VARCHAR(3),
        gatewayV6 VARCHAR(255),
        PRIMARY KEY (id),
        CHECK (leased IN (0, 1)),
        CHECK (allocated IN (0, 1)),
        CHECK (deleted IN (0, 1)),
        CHECK (reserved IN (0, 1))
    );

    INSERT INTO fixed_ips_backup
        SELECT id,
               address,
               network_id,
               instance_id,
               allocated,
               leased,
               reserved,
               created_at,
               updated_at,
               deleted_at,
               deleted,
               addressV6,
               netmaskV6,
               gatewayV6
        FROM fixed_ips;

    DROP TABLE fixed_ips;

    CREATE TABLE fixed_ips (
        id INTEGER NOT NULL,
        address VARCHAR(255),
        network_id INTEGER,
        instance_id INTEGER,
        allocated BOOLEAN DEFAULT FALSE,
        leased BOOLEAN DEFAULT FALSE,
        reserved BOOLEAN DEFAULT FALSE,
        created_at DATETIME NOT NULL,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN NOT NULL,
        PRIMARY KEY (id),
        CHECK (leased IN (0, 1)),
        CHECK (allocated IN (0, 1)),
        CHECK (deleted IN (0, 1)),
        CHECK (reserved IN (0, 1))
    );

    INSERT INTO fixed_ips
        SELECT id,
               address,
               network_id,
               instance_id,
               allocated,
               leased,
               reserved,
               created_at,
               updated_at,
               deleted_at,
               deleted
        FROM fixed_ips_backup;

    DROP TABLE fixed_ips_backup;

COMMIT;
