# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from sqlalchemy import MetaData

meta = MetaData()


def upgrade(migrate_engine):
    meta.bind = migrate_engine

    # NOTE (ironcamel): The only table we are not converting to utf8 here is
    # dns_domains. This table has a primary key that is 512 characters wide.
    # When the mysql engine attempts to convert it to utf8, it complains about
    # not supporting key columns larger than 1000.

    if migrate_engine.name == "mysql":
        # The instances table has to be converted early on. Also, the
        # foreign_key_checks has to be disabled inside of the execute command
        # that converts the instances table.
        migrate_engine.execute("SET foreign_key_checks = 0;"
            "ALTER TABLE instances CONVERT TO CHARACTER SET utf8")
        tables = ["agent_builds", "aggregate_hosts", "aggregate_metadata",
            "aggregates", "auth_tokens", "block_device_mapping",
            "bw_usage_cache", "certificates", "compute_nodes", "console_pools",
            "consoles", "fixed_ips", "floating_ips", "instance_actions",
            "instance_faults", "instance_info_caches", "instance_metadata",
            "instance_type_extra_specs", "instance_types", "iscsi_targets",
            "key_pairs", "migrate_version", "migrations", "networks",
            "projects", "provider_fw_rules", "quotas", "s3_images",
            "security_group_instance_association", "security_group_rules",
            "security_groups", "services", "sm_backend_config", "sm_flavors",
            "sm_volume", "snapshots", "snapshots", "user_project_association",
            "user_project_role_association", "user_role_association", "users",
            "virtual_interfaces", "virtual_storage_arrays", "volume_metadata",
            "volumes", "volume_type_extra_specs", "volume_types", "zones"]
        for table in tables:
            migrate_engine.execute(
                "ALTER TABLE %s CONVERT TO CHARACTER SET utf8" % table)
        migrate_engine.execute("SET foreign_key_checks = 1")
        migrate_engine.execute(
            "ALTER DATABASE nova DEFAULT CHARACTER SET utf8")


def downgrade(migrate_engine):
    # utf8 tables should be backwards compatible, so lets leave it alone
    pass
