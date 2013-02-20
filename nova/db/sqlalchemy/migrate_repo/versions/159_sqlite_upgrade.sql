BEGIN TRANSACTION;
    /* Create a backup table with the new fields size */
    CREATE TABLE networks_backup(
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted INTEGER,
        id INTEGER NOT NULL,
        injected BOOLEAN,
        cidr VARCHAR(43),
        netmask VARCHAR(39),
        bridge VARCHAR(255),
        gateway VARCHAR(39),
        broadcast VARCHAR(39),
        dns1 VARCHAR(39),
        vlan INTEGER,
        vpn_public_address VARCHAR(39),
        vpn_public_port INTEGER,
        vpn_private_address VARCHAR(39),
        dhcp_start VARCHAR(39),
        project_id VARCHAR(255),
        host VARCHAR(255),
        cidr_v6 VARCHAR(43),
        gateway_v6 VARCHAR(39),
        label VARCHAR(255),
        netmask_v6 VARCHAR(39),
        bridge_interface VARCHAR(255),
        multi_host BOOLEAN,
        dns2 VARCHAR(39),
        uuid VARCHAR(36),
        priority INTEGER,
        rxtx_base INTEGER,
        PRIMARY KEY (id)
    );

    /* get data from networks and the drop it */
    INSERT INTO networks_backup SELECT * FROM networks;
    DROP TABLE networks;

    CREATE TABLE networks (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted INTEGER,
        id INTEGER NOT NULL,
        injected BOOLEAN,
        cidr VARCHAR(43),
        netmask VARCHAR(39),
        bridge VARCHAR(255),
        gateway VARCHAR(39),
        broadcast VARCHAR(39),
        dns1 VARCHAR(39),
        vlan INTEGER,
        vpn_public_address VARCHAR(39),
        vpn_public_port INTEGER,
        vpn_private_address VARCHAR(39),
        dhcp_start VARCHAR(39),
        project_id VARCHAR(255),
        host VARCHAR(255),
        cidr_v6 VARCHAR(43),
        gateway_v6 VARCHAR(39),
        label VARCHAR(255),
        netmask_v6 VARCHAR(39),
        bridge_interface VARCHAR(255),
        multi_host BOOLEAN,
        dns2 VARCHAR(39),
        uuid VARCHAR(36),
        priority INTEGER,
        rxtx_base INTEGER,
        PRIMARY KEY (id),
        CHECK (injected IN (0, 1)),
        CHECK (multi_host IN (0, 1)),
        CONSTRAINT uniq_vlan_x_deleted UNIQUE (vlan, deleted)
    );

    /* get data from networks_backup back and drop it */
    INSERT INTO networks SELECT * FROM networks_backup;
    DROP TABLE networks_backup;
COMMIT;
