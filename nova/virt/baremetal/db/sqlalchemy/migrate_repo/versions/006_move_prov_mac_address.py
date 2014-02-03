# Copyright (c) 2013 NTT DOCOMO, INC.
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

from nova.openstack.common import log as logging
from sqlalchemy import and_, MetaData, select, Table, exists
from sqlalchemy import exc

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    nodes = Table('bm_nodes', meta, autoload=True)
    ifs = Table('bm_interfaces', meta, autoload=True)

    q = select([nodes.c.id, nodes.c.prov_mac_address],
               from_obj=nodes)

    # Iterate all elements before starting insert since IntegrityError
    # may disturb the iteration.
    node_address = {}
    for node_id, address in q.execute():
        node_address[node_id] = address

    i = ifs.insert()
    for node_id, address in node_address.iteritems():
        try:
            i.execute({'bm_node_id': node_id, 'address': address})
        except exc.IntegrityError:
            # The address is registered in both bm_nodes and bm_interfaces.
            # It is expected.
            pass


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    nodes = Table('bm_nodes', meta, autoload=True)
    ifs = Table('bm_interfaces', meta, autoload=True)

    subq = exists().where(and_(ifs.c.bm_node_id == nodes.c.id,
                               ifs.c.address == nodes.c.prov_mac_address))

    ifs.delete().where(subq).execute()

    # NOTE(arata):
    # In fact, this downgrade may not return the db to the previous state.
    # It seems to be not so match a problem, so this is just for memo.
    #
    # Think these two state before upgrading:
    #
    # (A) address 'x' is duplicate
    #     bm_nodes.prov_mac_address='x'
    #     bm_interfaces.address=['x', 'y']
    #
    # (B) no address is duplicate
    #     bm_nodes.prov_mac_address='x'
    #     bm_interfaces.address=['y']
    #
    # Upgrading them results in the same state:
    #
    #     bm_nodes.prov_mac_address='x'
    #     bm_interfaces.address=['x', 'y']
    #
    # Downgrading this results in B, even if the actual initial status was A
    # Of course we can change it to downgrade to B, but then we cannot
    # downgrade to A; it is an exclusive choice since we do not have
    # information about the initial state.
