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

from sqlalchemy import *
from migrate import *

from nova import log as logging

meta = MetaData()

# mac address table to add to DB
mac_addresses = Table('mac_addresses', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', Integer(),  primary_key=True, nullable=False),
        Column('mac_address',
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


def upgrade(migrate_engine):
    meta.bind = migrate_engine

    # grab tables and (column for dropping later)
    instances = Table('instances', meta, autoload=True)
    fixed_ips = Table('fixed_ips', meta, autoload=True)
    networks = Table('networks', meta, autoload=True)
    c = instances.columns['mac_address']

    # create mac_addresses table
    try:
        mac_addresses.create()
    except Exception as e:
        logging.error(_("Table |%s| not created!"), repr(mac_addresses))
        raise e

    # extract data from existing instance and fixed_ip tables
    s = select([instances.c.id, instances.c.mac_address,
                fixed_ips.c.network_id],
               fixed_ips.c.instance_id == instances.c.id)
    keys = ['instance_id', 'mac_address', 'network_id']
    join_list = [dict(zip(keys, row)) for row in s.execute()]
    logging.info("join list |%s|", join_list)

    # insert data into the table
    i = mac_addresses.insert()
    i.execute(join_list)

    # drop the mac_address column from instances
    c.drop
