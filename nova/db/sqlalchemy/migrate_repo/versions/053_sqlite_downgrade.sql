BEGIN TRANSACTION;

    CREATE TEMPORARY TABLE block_device_mapping_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        instance_id INTEGER NOT NULL,
        device_name VARCHAR(255) NOT NULL,
        delete_on_termination BOOLEAN,
        virtual_name VARCHAR(255),
        snapshot_id INTEGER,
        volume_id INTEGER,
        volume_size INTEGER,
        no_device BOOLEAN,
        connection_info TEXT,
        PRIMARY KEY (id),
        FOREIGN KEY(snapshot_id) REFERENCES snapshots (id),
        CHECK (deleted IN (0, 1)),
        CHECK (delete_on_termination IN (0, 1)),
        CHECK (no_device IN (0, 1)),
        FOREIGN KEY(volume_id) REFERENCES volumes (id),
        FOREIGN KEY(instance_id) REFERENCES instances (id)
    );

    INSERT INTO block_device_mapping_backup
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               instance_id,
               device_name,
               delete_on_termination,
               virtual_name,
               snapshot_id,
               volume_id,
               volume_size,
               no_device,
               connection_info
        FROM block_device_mapping;

    DROP TABLE block_device_mapping;

    CREATE TABLE block_device_mapping (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        instance_id INTEGER NOT NULL,
        device_name VARCHAR(255) NOT NULL,
        delete_on_termination BOOLEAN,
        virtual_name VARCHAR(255),
        snapshot_id INTEGER,
        volume_id INTEGER,
        volume_size INTEGER,
        no_device BOOLEAN,
        PRIMARY KEY (id),
        FOREIGN KEY(snapshot_id) REFERENCES snapshots (id),
        CHECK (deleted IN (0, 1)),
        CHECK (delete_on_termination IN (0, 1)),
        CHECK (no_device IN (0, 1)),
        FOREIGN KEY(volume_id) REFERENCES volumes (id),
        FOREIGN KEY(instance_id) REFERENCES instances (id)
    );

    INSERT INTO block_device_mapping
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               instance_id,
               device_name,
               delete_on_termination,
               virtual_name,
               snapshot_id,
               volume_id,
               volume_size,
               no_device
        FROM block_device_mapping_backup;

    DROP TABLE block_device_mapping_backup;

COMMIT;
