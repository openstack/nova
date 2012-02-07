BEGIN TRANSACTION;

    CREATE TEMPORARY TABLE volumes_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        ec2_id VARCHAR(255),
        user_id VARCHAR(255),
        project_id VARCHAR(255),
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
        provider_location VARCHAR(256),
        provider_auth VARCHAR(256),
        snapshot_id INTEGER,
        volume_type_id INTEGER,
        PRIMARY KEY (id),
        FOREIGN KEY(instance_id) REFERENCES instances (id),
        CHECK (deleted IN (0, 1))
    );

    INSERT INTO volumes_backup
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               ec2_id,
               user_id,
               project_id,
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
               snapshot_id,
               volume_type_id
        FROM volumes;

    DROP TABLE volumes;

    CREATE TABLE volumes (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        ec2_id VARCHAR(255),
        user_id VARCHAR(255),
        project_id VARCHAR(255),
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
        provider_location VARCHAR(256),
        provider_auth VARCHAR(256),
        snapshot_id INTEGER,
        PRIMARY KEY (id),
        FOREIGN KEY(instance_id) REFERENCES instances (id),
        CHECK (deleted IN (0, 1))
    );

    INSERT INTO volumes
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               ec2_id,
               user_id,
               project_id,
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
               snapshot_id
        FROM volumes_backup;

    DROP TABLE volumes_backup;

    DROP TABLE volume_type_extra_specs;

    DROP TABLE volume_types;

    DROP TABLE volume_metadata;

COMMIT;
