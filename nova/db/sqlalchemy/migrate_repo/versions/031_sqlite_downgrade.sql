BEGIN TRANSACTION;

    CREATE TEMPORARY TABLE fixed_ips_backup (
        id INTEGER NOT NULL,
        address VARCHAR(255),
        virtual_interface_id INTEGER,
        network_id INTEGER,
        instance_id INTEGER,
        allocated BOOLEAN default FALSE,
        leased BOOLEAN default FALSE,
        reserved BOOLEAN default FALSE,
        created_at DATETIME NOT NULL,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(virtual_interface_id) REFERENCES virtual_interfaces (id)
    );

    INSERT INTO fixed_ips_backup
    SELECT id, address, virtual_interface_id, network_id, instance_id, allocated, leased, reserved, created_at, updated_at, deleted_at, deleted
    FROM fixed_ips;

    DROP TABLE fixed_ips;

    CREATE TABLE fixed_ips (
        id INTEGER NOT NULL,
        address VARCHAR(255),
        virtual_interface_id INTEGER,
        network_id INTEGER,
        instance_id INTEGER,
        allocated BOOLEAN default FALSE,
        leased BOOLEAN default FALSE,
        reserved BOOLEAN default FALSE,
        created_at DATETIME NOT NULL,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN NOT NULL,
        PRIMARY KEY (id)
    );

    INSERT INTO fixed_ips
    SELECT id, address, virtual_interface_id, network_id, instance_id, allocated, leased, reserved, created_at, updated_at, deleted_at, deleted
    FROM fixed_ips;

    DROP TABLE fixed_ips_backup;

COMMIT;
