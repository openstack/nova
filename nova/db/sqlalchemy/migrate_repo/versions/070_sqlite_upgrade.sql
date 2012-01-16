BEGIN TRANSACTION;
    CREATE TABLE fixed_ips_backup (
            created_at DATETIME NOT NULL,
            updated_at DATETIME,
            deleted_at DATETIME,
            deleted BOOLEAN NOT NULL,
            id INTEGER NOT NULL,
            address VARCHAR(255),
            virtual_interface_id INTEGER,
            network_id INTEGER,
            instance_id INTEGER,
            allocated BOOLEAN default FALSE,
            leased BOOLEAN default FALSE,
            reserved BOOLEAN default FALSE,
            host VARCHAR(255),
            PRIMARY KEY (id)
        );

    CREATE TABLE floating_ips_backup (
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
        pool VARCHAR(255),
        interface VARCHAR(255),
        PRIMARY KEY (id)
    );

    INSERT INTO fixed_ips_backup
        SELECT created_at, updated_at, deleted_at, deleted, id, address,
                virtual_interface_id, network_id, instance_id, allocated,
                leased, reserved, host
        FROM fixed_ips;

    INSERT INTO floating_ips_backup
        SELECT created_at, updated_at, deleted_at, deleted, id, address,
                fixed_ip_id, project_id, host, auto_assigned, pool,
                interface
        FROM floating_ips;

    DROP TABLE fixed_ips;
    DROP TABLE floating_ips;

    CREATE TABLE fixed_ips (
            created_at DATETIME NOT NULL,
            updated_at DATETIME,
            deleted_at DATETIME,
            deleted BOOLEAN NOT NULL,
            id INTEGER NOT NULL,
            address VARCHAR(255),
            virtual_interface_id INTEGER,
            network_id INTEGER,
            instance_id INTEGER,
            allocated BOOLEAN default FALSE,
            leased BOOLEAN default FALSE,
            reserved BOOLEAN default FALSE,
            host VARCHAR(255),
            PRIMARY KEY (id)
        );

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
        auto_assigned BOOLEAN,
        pool VARCHAR(255),
        interface VARCHAR(255),
        PRIMARY KEY (id),
        CHECK (deleted IN (0, 1))
    );

    INSERT INTO fixed_ips
        SELECT created_at, updated_at, deleted_at, deleted, id, address,
                virtual_interface_id, network_id, instance_id, allocated,
                leased, reserved, host
        FROM fixed_ips_backup;

    INSERT INTO floating_ips
        SELECT created_at, updated_at, deleted_at, deleted, id, address,
                fixed_ip_id, project_id, host, auto_assigned, pool,
                interface
        FROM floating_ips_backup;

    DROP TABLE fixed_ips_backup;
    DROP TABLE floating_ips_backup;

COMMIT;
