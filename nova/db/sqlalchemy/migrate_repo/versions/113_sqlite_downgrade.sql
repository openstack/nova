BEGIN TRANSACTION;
    CREATE TEMPORARY TABLE fixed_ips_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        address VARCHAR(255),
	network_id INTEGER,
	instance_id INTEGER NOT NULL,
	instance_uuid VARCHAR(36),
	allocated BOOLEAN,
	leased BOOLEAN,
	reserved BOOLEAN,
	virtual_interface_id INTEGER,
	host VARCHAR(255),
        PRIMARY KEY (id)
    );

    INSERT INTO fixed_ips_backup
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
	       address,
	       network_id,
	       NULL,
               instance_uuid,
	       allocated,
	       leased,
	       reserved,
	       virtual_interface_id,
	       host
        FROM fixed_ips;

    UPDATE fixed_ips_backup
        SET instance_id=
            (SELECT id
                 FROM instances
                 WHERE fixed_ips_backup.instance_uuid = instances.uuid
    );

    DROP TABLE fixed_ips;

    CREATE TABLE fixed_ips (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        address VARCHAR(255),
	network_id INTEGER,
	instance_id INTEGER,
	allocated BOOLEAN,
	leased BOOLEAN,
	reserved BOOLEAN,
	virtual_interface_id INTEGER,
	host VARCHAR(255),
        PRIMARY KEY (id),
        FOREIGN KEY(instance_id) REFERENCES instances (id)
    );

    CREATE INDEX fixed_ips_id ON fixed_ips(id);
    CREATE INDEX address ON fixed_ips(address);

    INSERT INTO fixed_ips
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               address,
	       network_id,
               instance_id,
	       allocated,
	       leased,
	       reserved,
	       virtual_interface_id,
	       host
        FROM fixed_ips_backup;

    DROP TABLE fixed_ips_backup;

COMMIT;