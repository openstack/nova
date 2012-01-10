# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
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
#    under the License.from sqlalchemy import *

from sqlalchemy import Column, MetaData, Table, String

from nova import flags


flags.DECLARE('default_floating_pool', 'nova.network.manager')
flags.DECLARE('public_interface', 'nova.network.linux_net')
FLAGS = flags.FLAGS

meta = MetaData()

pool_column = Column('pool', String(255))
interface_column = Column('interface', String(255))


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    table = Table('floating_ips', meta, autoload=True)
    table.create_column(pool_column)
    table.create_column(interface_column)
    table.update().values(pool=FLAGS.default_floating_pool,
                          interface=FLAGS.public_interface).execute()


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    table = Table('floating_ips', meta, autoload=True)
    table.c.pool.drop()
    table.c.interface.drop()
