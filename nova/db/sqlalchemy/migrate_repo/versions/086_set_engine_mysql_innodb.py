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

from sqlalchemy import MetaData


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta = MetaData()
    meta.bind = migrate_engine
    if migrate_engine.name == "mysql":
        migrate_engine.execute("ALTER TABLE agent_builds Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE aggregate_hosts Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE aggregate_metadata Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE aggregates Engine=InnoDB")
        migrate_engine.execute(
            "ALTER TABLE block_device_mapping Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE bw_usage_cache Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE dns_domains Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE instance_faults Engine=InnoDB")
        migrate_engine.execute(
            "ALTER TABLE instance_type_extra_specs Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE provider_fw_rules Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE quota_classes Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE s3_images Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE sm_backend_config Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE sm_flavors Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE sm_volume Engine=InnoDB")
        migrate_engine.execute(
            "ALTER TABLE virtual_storage_arrays Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE volume_metadata Engine=InnoDB")
        migrate_engine.execute(
            "ALTER TABLE volume_type_extra_specs Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE volume_types Engine=InnoDB")


def downgrade(migrate_engine):
    pass
