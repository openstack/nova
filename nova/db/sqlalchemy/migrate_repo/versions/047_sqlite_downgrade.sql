BEGIN TRANSACTION;
    CREATE TEMPORARY TABLE virtual_interfaces_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        address VARCHAR(255),
        network_id INTEGER,
        instance_id INTEGER NOT NULL,
        uuid VARCHAR(36),
        PRIMARY KEY (id)
    );

    INSERT INTO virtual_interfaces_backup
        SELECT created_at, updated_at, deleted_at, deleted, id, address,
                network_id, instance_id, uuid
        FROM virtual_interfaces;

    DROP TABLE virtual_interfaces;

    CREATE TABLE virtual_interfaces (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        address VARCHAR(255),
        network_id INTEGER,
        instance_id INTEGER NOT NULL,
        uuid VARCHAR(36),
        PRIMARY KEY (id),
        FOREIGN KEY(network_id) REFERENCES networks (id),
        FOREIGN KEY(instance_id) REFERENCES instances (id),
        UNIQUE (address),
        CHECK (deleted IN (0, 1))
    );

    INSERT INTO virtual_interfaces
        SELECT created_at, updated_at, deleted_at, deleted, id, address,
                network_id, instance_id, uuid
        FROM virtual_interfaces_backup;

    DROP TABLE virtual_interfaces_backup;

COMMIT;
