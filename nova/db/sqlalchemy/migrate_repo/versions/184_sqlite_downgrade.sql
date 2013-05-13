BEGIN TRANSACTION;
    /* create networks_backup table with the fields like networks was before
    the upgrade */
    CREATE TABLE shadow_networks_backup(
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted INTEGER,
        id INTEGER NOT NULL,
        injected BOOLEAN,
        cidr VARCHAR(43),
        netmask VARCHAR(43),
        bridge VARCHAR(255),
        gateway VARCHAR(43),
        broadcast VARCHAR(43),
        dns1 VARCHAR(43),
        vlan INTEGER,
        vpn_public_address VARCHAR(43),
        vpn_public_port INTEGER,
        vpn_private_address VARCHAR(43),
        dhcp_start VARCHAR(43),
        project_id VARCHAR(255),
        host VARCHAR(255),
        cidr_v6 VARCHAR(43),
        gateway_v6 VARCHAR(43),
        label VARCHAR(255),
        netmask_v6 VARCHAR(43),
        bridge_interface VARCHAR(255),
        multi_host BOOLEAN,
        dns2 VARCHAR(43),
        uuid VARCHAR(36),
        priority INTEGER,
        rxtx_base INTEGER,
        PRIMARY KEY (id)
    );

    /* copy data currently on networks to the backup table and drop networks
    table */
    INSERT INTO shadow_networks_backup SELECT * FROM shadow_networks;
    DROP TABLE shadow_networks;

    CREATE TABLE shadow_networks (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted INTEGER,
        id INTEGER NOT NULL,
        injected BOOLEAN,
        cidr VARCHAR(43),
        netmask VARCHAR(43),
        bridge VARCHAR(255),
        gateway VARCHAR(43),
        broadcast VARCHAR(43),
        dns1 VARCHAR(43),
        vlan INTEGER,
        vpn_public_address VARCHAR(43),
        vpn_public_port INTEGER,
        vpn_private_address VARCHAR(43),
        dhcp_start VARCHAR(43),
        project_id VARCHAR(255),
        host VARCHAR(255),
        cidr_v6 VARCHAR(43),
        gateway_v6 VARCHAR(43),
        label VARCHAR(255),
        netmask_v6 VARCHAR(43),
        bridge_interface VARCHAR(255),
        multi_host BOOLEAN,
        dns2 VARCHAR(43),
        uuid VARCHAR(36),
        priority INTEGER,
        rxtx_base INTEGER,
        PRIMARY KEY (id)
    );

    /* Get  data from backup table and drop it next */
    INSERT INTO shadow_networks SELECT * FROM shadow_networks_backup;
    DROP TABLE shadow_networks_backup;
COMMIT;
