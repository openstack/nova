# Copyright 2013 Mirantis Inc.
# All Rights Reserved
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
#
# vim: tabstop=4 shiftwidth=4 softtabstop=4

from nova.db.sqlalchemy import utils


data = {
    # table_name: ((index_name_1, (*old_columns), (*new_columns)), ...)
    "certificates": (
        ("certificates_project_id_deleted_idx",
         ("project_id",), ("project_id", "deleted")),
        ("certificates_user_id_deleted_idx",
         ("user_id",), ("user_id", "deleted")),
    ),
    "instances": (
        ("instances_host_deleted_idx", ("host",), ("host", "deleted")),
        ("instances_uuid_deleted_idx", ("uuid",), ("uuid", "deleted")),
        ("instances_host_node_deleted_idx",
         ("host", "node"), ("host", "node", "deleted")),
    ),
    "iscsi_targets": (
        ("iscsi_targets_host_volume_id_deleted_idx",
         ("host", "volume_id"), ("host", "volume_id", "deleted")),
    ),
    "networks": (
        ("networks_bridge_deleted_idx", ("bridge",), ("bridge", "deleted")),
        ("networks_project_id_deleted_idx",
         ("project_id",), ("project_id", "deleted")),
        ("networks_uuid_project_id_deleted_idx",
         ("uuid", "project_id"), ("uuid", "project_id", "deleted")),
        ("networks_vlan_deleted_idx", ("vlan",), ("vlan", "deleted")),
    ),
    "fixed_ips": (
        ("fixed_ips_network_id_host_deleted_idx",
         ("network_id", "host"), ("network_id", "host", "deleted")),
        ("fixed_ips_address_reserved_network_id_deleted_idx",
         ("address", "reserved", "network_id"),
         ("address", "reserved", "network_id", "deleted")),
        ("fixed_ips_deleted_allocated_idx",
         ("address", "allocated"),
         ('address', 'deleted', 'allocated')),
    ),
    "floating_ips": (
        ("floating_ips_pool_deleted_fixed_ip_id_project_id_idx",
         ("pool", "fixed_ip_id", "project_id"),
         ("pool", "deleted", "fixed_ip_id", "project_id")),
    ),
    "instance_faults": (
        ("instance_faults_instance_uuid_deleted_created_at_idx",
         ("instance_uuid", "created_at"),
         ("instance_uuid", "deleted", "created_at")),
    ),
}


def upgrade(migrate_engine):
    return utils.modify_indexes(migrate_engine, data)


def downgrade(migrate_engine):
    return utils.modify_indexes(migrate_engine, data, upgrade=False)
