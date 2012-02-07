BEGIN TRANSACTION;

    DROP TABLE certificates;

    DROP TABLE console_pools;

    DROP TABLE consoles;

    DROP TABLE instance_actions;

    DROP TABLE iscsi_targets;

    CREATE TEMPORARY TABLE auth_tokens_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        token_hash VARCHAR(255) NOT NULL,
        user_id VARCHAR(255),
        server_manageent_url VARCHAR(255),
        storage_url VARCHAR(255),
        cdn_management_url VARCHAR(255),
        PRIMARY KEY (token_hash),
        CHECK (deleted IN (0, 1))
    );

    INSERT INTO auth_tokens_backup
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               token_hash,
               user_id,
               server_manageent_url,
               storage_url,
               cdn_management_url
        FROM auth_tokens;

    DROP TABLE auth_tokens;

    CREATE TABLE auth_tokens (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        token_hash VARCHAR(255) NOT NULL,
        user_id INTEGER,
        server_manageent_url VARCHAR(255),
        storage_url VARCHAR(255),
        cdn_management_url VARCHAR(255),
        PRIMARY KEY (token_hash),
        CHECK (deleted IN (0, 1))
    );

    INSERT INTO auth_tokens
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               token_hash,
               user_id,
               server_manageent_url,
               storage_url,
               cdn_management_url
        FROM auth_tokens_backup;

    DROP TABLE auth_tokens_backup;

    CREATE TEMPORARY TABLE instances_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        internal_id INTEGER,
        admin_pass VARCHAR(255),
        user_id VARCHAR(255),
        project_id VARCHAR(255),
        image_id VARCHAR(255),
        kernel_id VARCHAR(255),
        ramdisk_id VARCHAR(255),
        server_name VARCHAR(255),
        launch_index INTEGER,
        key_name VARCHAR(255),
        key_data TEXT,
        state INTEGER,
        state_description VARCHAR(255),
        memory_mb INTEGER,
        vcpus INTEGER,
        local_gb INTEGER,
        hostname VARCHAR(255),
        host VARCHAR(255),
        instance_type VARCHAR(255),
        user_data TEXT,
        reservation_id VARCHAR(255),
        mac_address VARCHAR(255),
        scheduled_at DATETIME,
        launched_at DATETIME,
        terminated_at DATETIME,
        display_name VARCHAR(255),
        display_description VARCHAR(255),
        availability_zone VARCHAR(255),
        locked BOOLEAN,
        PRIMARY KEY (id),
        CHECK (deleted IN (0, 1)),
        CHECK (locked IN (0, 1))
    );

    INSERT INTO instances_backup
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               internal_id,
               admin_pass,
               user_id,
               project_id,
               image_id,
               kernel_id,
               ramdisk_id,
               server_name,
               launch_index,
               key_name,
               key_data,
               state,
               state_description,
               memory_mb,
               vcpus,
               local_gb,
               hostname,
               host,
               instance_type,
               user_data,
               reservation_id,
               mac_address,
               scheduled_at,
               launched_at,
               terminated_at,
               display_name,
               display_description,
               availability_zone,
               locked
        FROM instances;

    DROP TABLE instances;

    CREATE TABLE instances (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        internal_id INTEGER,
        admin_pass VARCHAR(255),
        user_id VARCHAR(255),
        project_id VARCHAR(255),
        image_id VARCHAR(255),
        kernel_id VARCHAR(255),
        ramdisk_id VARCHAR(255),
        server_name VARCHAR(255),
        launch_index INTEGER,
        key_name VARCHAR(255),
        key_data TEXT,
        state INTEGER,
        state_description VARCHAR(255),
        memory_mb INTEGER,
        vcpus INTEGER,
        local_gb INTEGER,
        hostname VARCHAR(255),
        host VARCHAR(255),
        instance_type VARCHAR(255),
        user_data TEXT,
        reservation_id VARCHAR(255),
        mac_address VARCHAR(255),
        scheduled_at DATETIME,
        launched_at DATETIME,
        terminated_at DATETIME,
        display_name VARCHAR(255),
        display_description VARCHAR(255),
        PRIMARY KEY (id),
        CHECK (deleted IN (0, 1))
    );

    INSERT INTO instances
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               internal_id,
               admin_pass,
               user_id,
               project_id,
               image_id,
               kernel_id,
               ramdisk_id,
               server_name,
               launch_index,
               key_name,
               key_data,
               state,
               state_description,
               memory_mb,
               vcpus,
               local_gb,
               hostname,
               host,
               instance_type,
               user_data,
               reservation_id,
               mac_address,
               scheduled_at,
               launched_at,
               terminated_at,
               display_name,
               display_description
        FROM instances_backup;

    DROP TABLE instances_backup;

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
               ra_server
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
               host
        FROM networks_backup;

    DROP TABLE networks_backup;

    CREATE TEMPORARY TABLE services_backup (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        host VARCHAR(255),
        binary VARCHAR(255),
        topic VARCHAR(255),
        report_count INTEGER NOT NULL,
        disabled BOOLEAN,
        availability_zone VARCHAR(255),
        PRIMARY KEY (id),
        CHECK (deleted IN (0, 1)),
        CHECK (disabled IN (0, 1))
    );

    INSERT INTO services_backup
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               host,
               binary,
               topic,
               report_count,
               disabled,
               availability_zone
        FROM services;

    DROP TABLE services;

    CREATE TABLE services (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted BOOLEAN,
        id INTEGER NOT NULL,
        host VARCHAR(255),
        binary VARCHAR(255),
        topic VARCHAR(255),
        report_count INTEGER NOT NULL,
        disabled BOOLEAN,
        PRIMARY KEY (id),
        CHECK (deleted IN (0, 1)),
        CHECK (disabled IN (0, 1))
    );

    INSERT INTO services
        SELECT created_at,
               updated_at,
               deleted_at,
               deleted,
               id,
               host,
               binary,
               topic,
               report_count,
               disabled
        FROM services_backup;

    DROP TABLE services_backup;

COMMIT;
