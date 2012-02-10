-- sqlalchemy-migrate is surprisingly broken when it comes to migrations
-- for sqlite. As a result, we have to do much of the work manually here

BEGIN TRANSACTION;
    CREATE TABLE instance_types_temp (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        name VARCHAR(255),
        id INTEGER NOT NULL,
        memory_mb INTEGER NOT NULL,
        vcpus INTEGER NOT NULL,
        root_gb INTEGER NOT NULL,
        ephemeral_gb INTEGER NOT NULL,
        swap INTEGER NOT NULL,
        rxtx_factor FLOAT,
        vcpu_weight INTEGER,
        flavorid VARCHAR(255),
        PRIMARY KEY (id),
        CHECK (deleted IN (0, 1))
    );
    INSERT INTO instance_types_temp SELECT
        created_at,
        updated_at,
        deleted_at,
        deleted,
        name,
        id,
        memory_mb,
        vcpus,
        root_gb,
        ephemeral_gb,
        swap,
        rxtx_factor,
        vcpu_weight,
        flavorid
    FROM instance_types;
    DROP TABLE instance_types;
    ALTER TABLE instance_types_temp RENAME TO instance_types;
    CREATE TABLE volume_types_temp (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        name VARCHAR(255),
        id INTEGER NOT NULL,
        PRIMARY KEY (id),
        CHECK (deleted IN (0, 1))
    );
    INSERT INTO volume_types_temp SELECT
        created_at,
        updated_at,
        deleted_at,
        deleted,
        name,
        id
    FROM volume_types;
    DROP TABLE volume_types;
    ALTER TABLE volume_types_temp RENAME TO volume_types;
COMMIT;
