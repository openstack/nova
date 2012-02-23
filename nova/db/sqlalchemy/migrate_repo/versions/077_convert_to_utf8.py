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


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # NOTE (ironcamel): The only table we are not converting to utf8 here is
    # dns_domains. This table has a primary key that is 512 characters wide.
    # When the mysql engine attempts to convert it to utf8, it complains about
    # not supporting key columns larger than 1000.

    if migrate_engine.name == "mysql":
        tables = [
            # tables that are FK parents, must be converted early
            "aggregates", "console_pools", "instance_types", "instances",
            "projects", "security_groups", "sm_backend_config", "sm_flavors",
            "snapshots", "user_project_association", "users", "volume_types",
            "volumes",
            # those that are children and others later
            "agent_builds", "aggregate_hosts", "aggregate_metadata",
            "auth_tokens", "block_device_mapping", "bw_usage_cache",
            "certificates", "compute_nodes", "consoles", "fixed_ips",
            "floating_ips", "instance_actions", "instance_faults",
            "instance_info_caches", "instance_metadata",
            "instance_type_extra_specs", "iscsi_targets", "key_pairs",
            "migrate_version", "migrations", "networks", "provider_fw_rules",
            "quotas", "s3_images", "security_group_instance_association",
            "security_group_rules", "services", "sm_volume",
            "user_project_role_association", "user_role_association",
            "virtual_interfaces", "virtual_storage_arrays", "volume_metadata",
            "volume_type_extra_specs", "zones"]
        sql = "SET foreign_key_checks = 0;"
        for table in tables:
            sql += "ALTER TABLE %s CONVERT TO CHARACTER SET utf8;" % table
        sql += "SET foreign_key_checks = 1;"
        sql += "ALTER DATABASE %s DEFAULT CHARACTER SET utf8;" \
            % migrate_engine.url.database
        migrate_engine.execute(sql)


def downgrade(migrate_engine):
    # utf8 tables should be backwards compatible, so lets leave it alone
    pass
