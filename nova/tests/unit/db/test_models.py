# Copyright 2016 OpenStack Foundation
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

from nova.db.sqlalchemy import api_models
from nova.db.sqlalchemy import models
from nova import test


class TestSoftDeletesDeprecated(test.NoDBTestCase):

    def test_no_new_soft_deletes(self):
        whitelist = [
            'agent_builds',
            'aggregate_hosts',
            'aggregate_metadata',
            'aggregates',
            'block_device_mapping',
            'bw_usage_cache',
            'cells',
            'certificates',
            'compute_nodes',
            'console_pools',
            'consoles',
            'dns_domains',
            'fixed_ips',
            'floating_ips',
            'instance_actions',
            'instance_actions_events',
            'instance_extra',
            'instance_faults',
            'instance_group_member',
            'instance_group_policy',
            'instance_groups',
            'instance_id_mappings',
            'instance_info_caches',
            'instance_metadata',
            'instance_system_metadata',
            'instance_type_extra_specs',
            'instance_type_projects',
            'instance_types',
            'instances',
            'key_pairs',
            'migrations',
            'networks',
            'pci_devices',
            'project_user_quotas',
            'provider_fw_rules',
            'quota_classes',
            'quota_usages',
            'quotas',
            'reservations',
            's3_images',
            'security_group_default_rules',
            'security_group_instance_association',
            'security_group_rules',
            'security_groups',
            'services',
            'snapshot_id_mappings',
            'snapshots',
            'task_log',
            'virtual_interfaces',
            'volume_id_mappings',
            'volume_usage_cache'
         ]

        # Soft deletes are deprecated. Whitelist the tables that currently
        # allow soft deletes. No new tables should be added to this whitelist.
        tables = []
        for base in [models.BASE, api_models.API_BASE]:
            for table_name, table in base.metadata.tables.items():
                columns = [column.name for column in table.columns]
                if 'deleted' in columns or 'deleted_at' in columns:
                    tables.append(table_name)
        self.assertEqual(whitelist, sorted(tables))
