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
                           rxtx_cap INTEGER,
                           rxtx_quota INTEGER,
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
               COALESCE(rxtx_factor, 1) * COALESCE ((SELECT  MIN(rxtx_base)
                                            FROM networks
                                            WHERE rxtx_base > 0), 1)
                                            as rxtx_cap,
               0 as rxtx_cap,
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
                rxtx_cap INTEGER NOT NULL,
                    rxtx_factor INTEGER NOT NULL,
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
                created_at datetime DEFAULT NULL,
                updated_at datetime DEFAULT NULL,
                deleted_at datetime DEFAULT NULL,
                deleted tinyint(1) DEFAULT NULL,
                id int(11) NOT NULL,
                injected tinyint(1) DEFAULT NULL,
                cidr varchar(255) DEFAULT NULL,
                netmask varchar(255) DEFAULT NULL,
                bridge varchar(255) DEFAULT NULL,
                gateway varchar(255) DEFAULT NULL,
                broadcast varchar(255) DEFAULT NULL,
                dns1 varchar(255) DEFAULT NULL,
                vlan int(11) DEFAULT NULL,
                vpn_public_address varchar(255) DEFAULT NULL,
                vpn_public_port int(11) DEFAULT NULL,
                vpn_private_address varchar(255) DEFAULT NULL,
                dhcp_start varchar(255) DEFAULT NULL,
                project_id varchar(255) DEFAULT NULL,
                host varchar(255) DEFAULT NULL,
                cidr_v6 varchar(255) DEFAULT NULL,
                gateway_v6 varchar(255) DEFAULT NULL,
                label varchar(255) DEFAULT NULL,
                netmask_v6 varchar(255) DEFAULT NULL,
                bridge_interface varchar(255) DEFAULT NULL,
                multi_host tinyint(1) DEFAULT NULL,
                dns2 varchar(255) DEFAULT NULL,
                uuid varchar(36) DEFAULT NULL,
                priority int(11) DEFAULT NULL,
                PRIMARY KEY (`id`)
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
