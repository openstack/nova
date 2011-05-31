# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

from sqlalchemy import MetaData, Table

meta = MetaData()


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine
    if migrate_engine.name == "mysql":
        migrate_engine.execute("ALTER TABLE auth_tokens Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE certificates Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE compute_nodes Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE console_pools Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE consoles Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE export_devices Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE fixed_ips Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE floating_ips Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE instance_actions Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE instance_metadata Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE instance_types Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE instances Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE iscsi_targets Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE key_pairs Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE migrate_version Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE migrations Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE networks Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE projects Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE quotas Engine=InnoDB")
        migrate_engine.execute(
         "ALTER TABLE security_group_instance_association Engine=InnoDB")
        migrate_engine.execute(
         "ALTER TABLE security_group_rules Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE security_groups Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE services Engine=InnoDB")
        migrate_engine.execute(
         "ALTER TABLE user_project_association Engine=InnoDB")
        migrate_engine.execute(
         "ALTER TABLE user_project_role_association Engine=InnoDB")
        migrate_engine.execute(
         "ALTER TABLE user_role_association Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE users Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE volumes Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE zones Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE snapshots Engine=InnoDB")


def downgrade(migrate_engine):
    meta.bind = migrate_engine
