BEGIN TRANSACTION;
    CREATE TEMPORARY TABLE instance_info_caches_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        network_info TEXT,
        instance_id VARCHAR(36),
        PRIMARY KEY (id)
    );

    INSERT INTO instance_info_caches_backup
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               network_info,
               instance_uuid as instance_id
        FROM instance_info_caches;

    DROP TABLE instance_info_caches;

    CREATE TABLE instance_info_caches (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        network_info TEXT,
        instance_id VARCHAR(36),
        PRIMARY KEY (id)
    );

    CREATE INDEX instance_info_caches_instance_id_idx ON instance_info_caches(instance_id);

    INSERT INTO instance_info_caches
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               network_info,
               instance_id
        FROM instance_info_caches_backup;

    DROP TABLE instance_info_caches_backup;

COMMIT;
