BEGIN TRANSACTION;

    -- change id and snapshot_id datatypes in volumes table
    CREATE TABLE volumes_backup(
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id VARCHAR(36) NOT NULL,
        ec2_id INTEGER,
        user_id VARCHAR(255),
        project_id VARCHAR(255),
        snapshot_id VARCHAR(36),
        host VARCHAR(255),
        size INTEGER,
        availability_zone VARCHAR(255),
        instance_id INTEGER,
        mountpoint VARCHAR(255),
        attach_time VARCHAR(255),
        status VARCHAR(255),
        attach_status VARCHAR(255),
        scheduled_at DATETIME,
        launched_at DATETIME,
        terminated_at DATETIME,
        display_name VARCHAR(255),
        display_description VARCHAR(255),
        provider_location VARCHAR(255),
        provider_auth VARCHAR(255),
        volume_type_id INTEGER,
        PRIMARY KEY (id),
        FOREIGN KEY(instance_id) REFERENCES instances (id),
        UNIQUE (id),
        CHECK (deleted IN (0, 1))
    );

    INSERT INTO volumes_backup SELECT
        created_at,
        updated_at,
        deleted_at,
        deleted,
        id,
        ec2_id,
        user_id,
        project_id,
        snapshot_id,
        host,
        size,
        availability_zone,
        instance_id,
        mountpoint,
        attach_time,
        status,
        attach_status,
        scheduled_at,
        launched_at,
        terminated_at,
        display_name,
        display_description,
        provider_location,
        provider_auth,
        volume_type_id
    FROM volumes;
    DROP TABLE volumes;
    ALTER TABLE volumes_backup RENAME TO volumes;

    -- change id and volume_id datatypes in snapshots table
    CREATE TABLE snapshots_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id VARCHAR(36) NOT NULL,
        user_id VARCHAR(255),
        project_id VARCHAR(255),
        volume_id VARCHAR(36),
        status VARCHAR(255),
        progress VARCHAR(255),
        volume_size INTEGER,
        display_name VARCHAR(255),
        display_description VARCHAR(255),
        PRIMARY KEY (id),
        UNIQUE (id),
        CHECK (deleted IN (0, 1))
    );
    INSERT INTO snapshots_backup SELECT
        created_at,
        updated_at,
        deleted_at,
        deleted,
        id,
        user_id,
        project_id,
        volume_id,
        status,
        progress,
        volume_size,
        display_name,
        display_description
    FROM snapshots;
    DROP TABLE snapshots;
    ALTER TABLE snapshots_backup RENAME TO snapshots;

    -- change id and volume_id datatypes in iscsi_targets table
    CREATE TABLE iscsi_targets_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        target_num INTEGER,
        host VARCHAR(255),
        volume_id VARCHAR(36),
        PRIMARY KEY (id),
        FOREIGN KEY(volume_id) REFERENCES volumes(id),
        UNIQUE (id),
        CHECK (deleted IN (0, 1))
    );
    INSERT INTO iscsi_targets_backup SELECT
        created_at,
        updated_at,
        deleted_at,
        deleted,
        id,
        target_num,
        host,
        volume_id
    FROM iscsi_targets;
    DROP TABLE iscsi_targets;
    ALTER TABLE iscsi_targets_backup RENAME TO iscsi_targets;

    CREATE TABLE volume_metadata_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        key VARCHAR(255),
        value VARCHAR(255),
        volume_id VARCHAR(36),
        PRIMARY KEY (id),
        FOREIGN KEY(volume_id) REFERENCES volumes(id),
        UNIQUE (id),
        CHECK (deleted IN (0, 1))
    );
    INSERT INTO volume_metadata_backup SELECT
        created_at,
        updated_at,
        deleted_at,
        deleted,
        id,
        key,
        value,
        volume_id
    FROM volume_metadata;
    DROP TABLE volume_metadata;
    ALTER TABLE volume_metadata_backup RENAME TO volume_metadata;

    -- change volume_id and snapshot_id datatypes in bdm table
    CREATE TABLE block_device_mapping_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        instance_uuid VARCHAR(36) NOT NULL,
        device_name VARCHAR(255),
        delete_on_termination BOOLEAN,
        virtual_name VARCHAR(255),
        snapshot_id VARCHAR(36),
        volume_id VARCHAR(36),
        volume_size INTEGER,
        no_device BOOLEAN,
        connection_info VARCHAR(255),
        FOREIGN KEY(instance_uuid) REFERENCES instances(id),
        FOREIGN KEY(volume_id) REFERENCES volumes(id),
        FOREIGN KEY(snapshot_id) REFERENCES snapshots(id),
        PRIMARY KEY (id),
        UNIQUE (id),
        CHECK (deleted IN (0, 1))
    );
    INSERT INTO block_device_mapping_backup SELECT
        created_at,
        updated_at,
        deleted_at,
        deleted,
        id,
        instance_uuid,
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
    ALTER TABLE block_device_mapping_backup RENAME TO block_device_mapping;

    -- change volume_id and sm_volume_table
    CREATE TABLE sm_volume_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id VARCHAR(36) NOT NULL,
        backend_id INTEGER NOT NULL,
        vdi_uuid VARCHAR(255),
        PRIMARY KEY (id),
        FOREIGN KEY(id) REFERENCES volumes(id),
        UNIQUE (id),
        CHECK (deleted IN (0,1))
    );
    INSERT INTO sm_volume_backup SELECT
        created_at,
        updated_at,
        deleted_at,
        deleted,
        id,
        backend_id,
        vdi_uuid
    FROM sm_volume;
    DROP TABLE sm_volume;
    ALTER TABLE sm_volume_backup RENAME TO sm_volume;

COMMIT;
