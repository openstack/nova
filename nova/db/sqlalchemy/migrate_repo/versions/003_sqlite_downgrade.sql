BEGIN TRANSACTION;

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
        ra_server VARCHAR(255),
        label VARCHAR(255),
        PRIMARY KEY (id),
        CHECK (deleted IN (0, 1)),
        CHECK (injected IN (0, 1))
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
               ra_server,
               label
        FROM networks;

    DROP TABLE networks;

    CREATE TABLE networks (
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
        ra_server VARCHAR(255),
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
               ra_server
        FROM networks_backup;

    DROP TABLE networks_backup;

COMMIT;
