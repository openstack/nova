# Copyright (c) 2014 Nebula, Inc.
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


from sqlalchemy import MetaData, Column, Table
from sqlalchemy import Boolean, Integer

from nova.db.sqlalchemy import types


def upgrade(migrate_engine):
    """Function adds network mtu, dhcp_server, and share_dhcp fields."""
    meta = MetaData(bind=migrate_engine)

    networks = Table('networks', meta, autoload=True)
    shadow_networks = Table('shadow_networks', meta, autoload=True)

    # NOTE(vish): ignore duplicate runs of upgrade so this can
    #             be backported
    mtu = Column('mtu', Integer)
    dhcp_server = Column('dhcp_server', types.IPAddress)
    enable_dhcp = Column('enable_dhcp', Boolean, default=True)
    share_address = Column('share_address', Boolean, default=False)

    if not hasattr(networks.c, 'mtu'):
        networks.create_column(mtu)
    if not hasattr(networks.c, 'dhcp_server'):
        networks.create_column(dhcp_server)
    if not hasattr(networks.c, 'enable_dhcp'):
        networks.create_column(enable_dhcp)
    if not hasattr(networks.c, 'share_address'):
        networks.create_column(share_address)

    if not hasattr(shadow_networks.c, 'mtu'):
        shadow_networks.create_column(mtu.copy())
    if not hasattr(shadow_networks.c, 'dhcp_server'):
        shadow_networks.create_column(dhcp_server.copy())
    if not hasattr(shadow_networks.c, 'enable_dhcp'):
        shadow_networks.create_column(enable_dhcp.copy())
    if not hasattr(shadow_networks.c, 'share_address'):
        shadow_networks.create_column(share_address.copy())
