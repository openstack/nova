BEGIN TRANSACTION;

    CREATE TEMPORARY TABLE zones_temp (
                           created_at DATETIME,
                           updated_at DATETIME,
                           deleted_at DATETIME,
                           deleted BOOLEAN,
                           id INTEGER NOT NULL,
                           name VARCHAR(255),
                           api_url VARCHAR(255),
                           username VARCHAR(255),
                           password VARCHAR(255),
                           weight_offset FLOAT,
                           weight_scale FLOAT,
                           PRIMARY KEY (id),
                           CHECK (deleted IN (0, 1))
    );

    INSERT INTO zones_temp
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               name,
               api_url,
               username,
               password,
               weight_offset,
               weight_scale FROM zones;

    DROP TABLE zones;

    ALTER TABLE zones_temp RENAME TO zones;
COMMIT;
