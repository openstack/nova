BEGIN TRANSACTION;

    CREATE TEMPORARY TABLE instance_types_backup (
                created_at DATETIME,
                updated_at DATETIME,
                deleted_at DATETIME,
                deleted BOOLEAN,
                name VARCHAR(255),
                id INTEGER NOT NULL,
                memory_mb INTEGER NOT NULL,
                vcpus INTEGER NOT NULL,
                local_gb INTEGER NOT NULL,
                swap INTEGER NOT NULL,
                rxtx_factor FLOAT,
                vcpu_weight INTEGER,
                flavorid VARCHAR(255),
                PRIMARY KEY (id),
                UNIQUE (flavorid),
                CHECK (deleted IN (0, 1)),
                UNIQUE (name)
    );

    INSERT INTO instance_types_backup
        SELECT created_at,
                updated_at,
                deleted_at,
                deleted,
                name,
                id,
                memory_mb,
                vcpus,
                local_gb,
                swap,
                COALESCE(rxtx_cap, 1) / COALESCE ((SELECT  MIN(rxtx_cap)
                                             FROM instance_types
                                             WHERE rxtx_cap > 0), 1) as rxtx_cap,
                vcpu_weight,
                flavorid
        FROM instance_types;

    ALTER TABLE networks ADD COLUMN rxtx_base INTEGER DEFAULT 1;

    UPDATE networks SET rxtx_base = COALESCE((SELECT MIN(rxtx_cap)
                                            FROM instance_types
                                            WHERE rxtx_cap>0), 1);

    DROP TABLE instance_types;

    CREATE TABLE instance_types (
            created_at DATETIME,
            updated_at DATETIME,
            deleted_at DATETIME,
            deleted BOOLEAN,
            name VARCHAR(255),
            id INTEGER NOT NULL,
            memory_mb INTEGER NOT NULL,
            vcpus INTEGER NOT NULL,
            local_gb INTEGER NOT NULL,
            swap INTEGER NOT NULL,
            rxtx_factor FLOAT,
            vcpu_weight INTEGER,
            flavorid VARCHAR(255),
            PRIMARY KEY (id),
            UNIQUE (flavorid),
            CHECK (deleted IN (0, 1)),
            UNIQUE (name)
    );

    INSERT INTO instance_types
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               name,
               id,
               memory_mb,
               vcpus,
               local_gb,
               swap,
               rxtx_factor,
               vcpu_weight,
               flavorid
        FROM instance_types_backup;

    DROP TABLE instance_types_backup;

COMMIT;
