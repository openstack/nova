BEGIN TRANSACTION;
    CREATE TEMPORARY TABLE security_group_instance_association_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        security_group_id INTEGER NOT NULL,
        instance_id INTEGER NOT NULL,
        instance_uuid VARCHAR(36),
        PRIMARY KEY (id)
    );

    INSERT INTO security_group_instance_association_backup
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               security_group_id,
               NULL,
               instance_uuid
        FROM security_group_instance_association;

    UPDATE security_group_instance_association_backup
        SET instance_id=
            (SELECT id
                 FROM instances
                 WHERE security_group_instance_association_backup.instance_uuid = instances.uuid
    );

    DROP TABLE security_group_instance_association;

    CREATE TABLE security_group_instance_association (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        security_group_id INTEGER NOT NULL,
        instance_id INTEGER NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(instance_id) REFERENCES instances (id)
    );

    CREATE INDEX security_group_instance_association_security_group_id_idx ON security_group_instance_association(security_group_id);
    CREATE INDEX security_group_instance_association_instance_id_idx ON security_group_instance_association(instance_id);

    INSERT INTO security_group_instance_association
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
	       security_group_id,
               instance_id
        FROM security_group_instance_association_backup;

    DROP TABLE security_group_instance_association_backup;

COMMIT;