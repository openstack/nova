# Copyright 2011 OpenStack LLC.
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

import datetime

from sqlalchemy import *
from migrate import *

from nova import log as logging

meta = MetaData()

# mac address table to add to DB
mac_addresses = Table('mac_addresses', meta,
        Column('created_at', DateTime(timezone=False),
               default=datetime.datetime.utcnow),
        Column('updated_at', DateTime(timezone=False),
               onupdate=datetime.datetime.utcnow),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', Integer(),  primary_key=True, nullable=False),
        Column('address',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False),
               unique=True),
        Column('network_id',
               Integer(),
               ForeignKey('networks.id'),
               nullable=False),
        Column('instance_id',
               Integer(),
               ForeignKey('instances.id'),
               nullable=False),
        )


# bridge_interface column to add to networks table
interface = Column('bridge_interface',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None, unicode_error=None,
                          _warn_on_bytestring=False),
                          nullable=True)


# mac_address column to add to fixed_ips table
mac_address = Column('mac_address_id',
                     Integer(),
                     ForeignKey('mac_addresses.id'),
                     nullable=True)


def upgrade(migrate_engine):
    meta.bind = migrate_engine

    # grab tables and (column for dropping later)
    instances = Table('instances', meta, autoload=True)
    fixed_ips = Table('fixed_ips', meta, autoload=True)
    networks = Table('networks', meta, autoload=True)
    c = instances.columns['mac_address']

    # add interface column to networks table
    # values will have to be set manually before running nova
    try:
        networks.create_column(interface)
    except Exception as e:
        logging.error(_("interface column not added to networks table"))
        raise e

    # create mac_addresses table
    try:
        mac_addresses.create()
    except Exception as e:
        logging.error(_("Table |%s| not created!"), repr(mac_addresses))
        raise e

    # add mac_address column to fixed_ips table
    try:
        fixed_ips.create_column(mac_address)
    except Exception as e:
        logging.error(_("mac_address column not added to fixed_ips table"))
        raise e

    # populate the mac_addresses table
    # extract data from existing instance and fixed_ip tables
    s = select([instances.c.id, instances.c.mac_address,
                fixed_ips.c.network_id],
               fixed_ips.c.instance_id == instances.c.id)
    keys = ('instance_id', 'address', 'network_id')
    join_list = [dict(zip(keys, row)) for row in s.execute()]
    logging.debug(_("join list for moving mac_addresses |%s|"), join_list)

    # insert data into the table
    if join_list:
        i = mac_addresses.insert()
        i.execute(join_list)

    # populate the fixed_ips mac_address column
    s = select([fixed_ips.c.id, fixed_ips.c.instance_id],
               fixed_ips.c.instance_id != None)

    for row in s.execute():
        m = select([mac_addresses.c.id].\
            where(mac_addresses.c.instance_id == row['instance_id'])).\
            as_scalar()
        u = fixed_ips.update().values(mac_address_id=m).\
            where(fixed_ips.c.id == row['id'])
        u.execute()

    # drop the mac_address column from instances
    c.drop()


def downgrade(migrate_engine):
    logging.error(_("Can't downgrade without losing data"))
    raise Exception
