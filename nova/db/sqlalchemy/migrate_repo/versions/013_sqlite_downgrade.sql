BEGIN TRANSACTION;

    CREATE TEMPORARY TABLE migrations_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        source_compute VARCHAR(255),
        dest_compute VARCHAR(255),
        dest_host VARCHAR(255),
        instance_id INTEGER,
        status VARCHAR(255),
        old_flavor_id INTEGER,
        new_flavor_id INTEGER,
        PRIMARY KEY (id),
        CHECK (deleted IN (0, 1)),
        FOREIGN KEY(instance_id) REFERENCES instances (id)
    );

    INSERT INTO migrations_backup
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               source_compute,
               dest_compute,
               dest_host,
               instance_id,
               status,
               old_flavor_id,
               new_flavor_id
        FROM migrations;

    DROP TABLE migrations;

    CREATE TABLE migrations (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        source_compute VARCHAR(255),
        dest_compute VARCHAR(255),
        dest_host VARCHAR(255),
        instance_id INTEGER,
        status VARCHAR(255),
        PRIMARY KEY (id),
        CHECK (deleted IN (0, 1)),
        FOREIGN KEY(instance_id) REFERENCES instances (id)
    );

    INSERT INTO migrations
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               source_compute,
               dest_compute,
               dest_host,
               instance_id,
               status
        FROM migrations_backup;

    DROP TABLE migrations_backup;

COMMIT;
