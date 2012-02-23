BEGIN TRANSACTION;

    CREATE TEMPORARY TABLE fixed_ips_backup (
            id INTEGER NOT NULL,
            address VARCHAR(255),
            virtual_interface_id INTEGER,
            network_id INTEGER,
            instance_id INTEGER,
            allocated BOOLEAN default FALSE,
            leased BOOLEAN default FALSE,
            reserved BOOLEAN default FALSE,
            created_at DATETIME NOT NULL,
            updated_at DATETIME,
            deleted_at DATETIME,
            deleted BOOLEAN NOT NULL,
            host VARCHAR(255),
            PRIMARY KEY (id),
            FOREIGN KEY(virtual_interface_id) REFERENCES virtual_interfaces (id)
    );

    INSERT INTO fixed_ips_backup
            SELECT id,
                   address,
                   virtual_interface_id,
                   network_id,
                   instance_id,
                   allocated,
                   leased,
                   reserved,
                   created_at,
                   updated_at,
                   deleted_at,
                   deleted,
                   host
            FROM fixed_ips;

    DROP TABLE fixed_ips;

    CREATE TABLE fixed_ips (
            id INTEGER NOT NULL,
            address VARCHAR(255),
            virtual_interface_id INTEGER,
            network_id INTEGER,
            instance_id INTEGER,
            allocated BOOLEAN default FALSE,
            leased BOOLEAN default FALSE,
            reserved BOOLEAN default FALSE,
            created_at DATETIME NOT NULL,
            updated_at DATETIME,
            deleted_at DATETIME,
            deleted BOOLEAN NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(virtual_interface_id) REFERENCES virtual_interfaces (id)
    );

    INSERT INTO fixed_ips
            SELECT id,
                   address,
                   virtual_interface_id,
                   network_id,
                   instance_id,
                   allocated,
                   leased,
                   reserved,
                   created_at,
                   updated_at,
                   deleted_at,
                   deleted
            FROM fixed_ips_backup;

    DROP TABLE fixed_ips_backup;

    CREATE TEMPORARY TABLE networks_backup (
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
        dns VARCHAR(255),
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
        PRIMARY KEY (id),
        CHECK (deleted IN (0, 1)),
        CHECK (injected IN (0, 1)),
        CHECK (multi_host IN (0, 1))
    );

    INSERT INTO networks_backup
        SELECT created_at,
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
               dns,
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
               multi_host
        FROM networks;

    DROP TABLE networks;

    CREATE TABLE networks(
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
        dns VARCHAR(255),
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
        PRIMARY KEY (id),
        CHECK (deleted IN (0, 1)),
        CHECK (injected IN (0, 1))
    );

    INSERT INTO networks
        SELECT created_at,
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
               dns,
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
               bridge_interface
        FROM networks_backup;

    DROP TABLE networks_backup;
COMMIT;
