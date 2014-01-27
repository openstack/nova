# Copyright (c) 2012 NTT DOCOMO, INC.
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

from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import Index, Integer, MetaData, String, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    bm_nodes = Table('bm_nodes', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('cpus', Integer),
        Column('memory_mb', Integer),
        Column('local_gb', Integer),
        Column('pm_address', String(length=255)),
        Column('pm_user', String(length=255)),
        Column('pm_password', String(length=255)),
        Column('service_host', String(length=255)),
        Column('prov_mac_address', String(length=255)),
        Column('instance_uuid', String(length=36)),
        Column('registration_status', String(length=16)),
        Column('task_state', String(length=255)),
        Column('prov_vlan_id', Integer),
        Column('terminal_port', Integer),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    bm_interfaces = Table('bm_interfaces', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('bm_node_id', Integer),
        Column('address', String(length=255), unique=True),
        Column('datapath_id', String(length=255)),
        Column('port_no', Integer),
        Column('vif_uuid', String(length=36), unique=True),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    bm_pxe_ips = Table('bm_pxe_ips', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('address', String(length=255), unique=True),
        Column('bm_node_id', Integer),
        Column('server_address', String(length=255), unique=True),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    bm_deployments = Table('bm_deployments', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('bm_node_id', Integer),
        Column('key', String(length=255)),
        Column('image_path', String(length=255)),
        Column('pxe_config_path', String(length=255)),
        Column('root_mb', Integer),
        Column('swap_mb', Integer),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    bm_nodes.create()
    bm_interfaces.create()
    bm_pxe_ips.create()
    bm_deployments.create()

    Index('idx_bm_nodes_service_host_deleted',
          bm_nodes.c.service_host, bm_nodes.c.deleted)\
          .create(migrate_engine)
    Index('idx_bm_nodes_instance_uuid_deleted',
          bm_nodes.c.instance_uuid, bm_nodes.c.deleted)\
          .create(migrate_engine)
    Index('idx_bm_nodes_hmcld',
          bm_nodes.c.service_host, bm_nodes.c.memory_mb, bm_nodes.c.cpus,
          bm_nodes.c.local_gb, bm_nodes.c.deleted)\
          .create(migrate_engine)

    Index('idx_bm_interfaces_bm_node_id_deleted',
          bm_interfaces.c.bm_node_id, bm_interfaces.c.deleted)\
          .create(migrate_engine)

    Index('idx_bm_pxe_ips_bm_node_id_deleted',
          bm_pxe_ips.c.bm_node_id, bm_pxe_ips.c.deleted)\
          .create(migrate_engine)


def downgrade(migrate_engine):
    raise NotImplementedError('Downgrade from 001_init is unsupported.')
