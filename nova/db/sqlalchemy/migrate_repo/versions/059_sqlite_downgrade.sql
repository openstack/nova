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
                           rxtx_quota INTEGER NOT NULL,
                           rxtx_cap INTEGER NOT NULL,
                           vcpu_weight INTEGER,
                           flavorid VARCHAR(255),
                           PRIMARY KEY (id),
                           CHECK (deleted IN (0, 1)),
                           UNIQUE (flavorid),
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
               0 as rxtx_quota,
               COALESCE(rxtx_factor, 1) * COALESCE ((SELECT  MIN(rxtx_base)
                                            FROM networks
                                            WHERE rxtx_base > 0), 1)
                                            as rxtx_cap,
               vcpu_weight,
               flavorid FROM instance_types;

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
                rxtx_quota INTEGER NOT NULL,
                rxtx_cap INTEGER NOT NULL,
                vcpu_weight INTEGER,
                flavorid VARCHAR(255),
                PRIMARY KEY (id),
                UNIQUE (flavorid),
                CHECK (deleted IN (0, 1)),
                UNIQUE (name)
    );

    INSERT INTO instance_types SELECT * FROM instance_types_backup;
    DROP TABLE instance_types_backup;

    CREATE TABLE networks_backup (
                created_at DATETIME,
                updated_at DATETIME,
                deleted_at DATETIME,
                deleted BOOLEAN,
                id INTEGER NOT NULL,
                injected BOOLEAN,
                cidr VARCHAR(255),
                netmask VARCHAR(255),
                bridge VARCHAR(255),
                gateway VARCHAR(255),
                broadcast VARCHAR(255),
                dns1 VARCHAR(255),
                vlan INTEGER,
                vpn_public_address VARCHAR(255),
                vpn_public_port INTEGER,
                vpn_private_address VARCHAR(255),
                dhcp_start VARCHAR(255),
                project_id VARCHAR(255),
                host VARCHAR(255),
                cidr_v6 VARCHAR(255),
                gateway_v6 VARCHAR(255),
                label VARCHAR(255),
                netmask_v6 VARCHAR(255),
                bridge_interface VARCHAR(255),
                multi_host BOOLEAN,
                dns2 VARCHAR(255),
                uuid VARCHAR(36),
                priority INTEGER,
                PRIMARY KEY (id),
                CHECK (deleted IN (0, 1)),
                CHECK (injected IN (0, 1)),
                CHECK (multi_host IN (0, 1))
    );

    INSERT INTO networks_backup
       SELECT   created_at,
                updated_at,
                deleted_at,
                deleted,
                id,
                injected,
                cidr,
                netmask,
                bridge,
                gateway,
                broadcast,
                dns1,
                vlan,
                vpn_public_address,
                vpn_public_port,
                vpn_private_address,
                dhcp_start,
                project_id,
                host,
                cidr_v6,
                gateway_v6,
                label,
                netmask_v6,
                bridge_interface,
                multi_host,
                dns2,
                uuid,
                priority
       FROM networks;

   DROP TABLE networks;
   ALTER TABLE networks_backup RENAME TO networks;
COMMIT;
