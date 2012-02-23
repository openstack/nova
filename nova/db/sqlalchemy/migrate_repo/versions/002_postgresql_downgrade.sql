BEGIN;

    DROP TABLE certificates;
    DROP TABLE consoles;
    DROP TABLE console_pools;
    DROP TABLE instance_actions;
    DROP TABLE iscsi_targets;

    ALTER TABLE auth_tokens ADD COLUMN user_id_backup INTEGER;
    UPDATE auth_tokens SET user_id_backup = CAST(user_id AS INTEGER);
    ALTER TABLE auth_tokens DROP COLUMN user_id;
    ALTER TABLE auth_tokens RENAME COLUMN user_id_backup TO user_id;

    ALTER TABLE instances DROP COLUMN availability_zone;
    ALTER TABLE instances DROP COLUMN locked;
    ALTER TABLE networks DROP COLUMN cidr_v6;
    ALTER TABLE networks DROP COLUMN ra_server;
    ALTER TABLE services DROP COLUMN availability_zone;

COMMIT;
