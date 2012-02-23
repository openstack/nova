# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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

from sqlalchemy import Column, Integer, MetaData, String, Table
from nova import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)

    types = {}
    for instance in migrate_engine.execute(instances.select()):
        if instance.instance_type_id is None:
            types[instance.id] = None
            continue
        try:
            types[instance.id] = int(instance.instance_type_id)
        except ValueError:
            LOG.warn("Instance %s did not have instance_type_id "
                         "converted to an integer because its value is %s" %
                          (instance.id, instance.instance_type_id))
            types[instance.id] = None

    integer_column = Column('instance_type_id_int', Integer(), nullable=True)
    string_column = instances.c.instance_type_id

    integer_column.create(instances)
    for instance_id, instance_type_id in types.iteritems():
        update = instances.update().\
                where(instances.c.id == instance_id).\
                values(instance_type_id_int=instance_type_id)
        migrate_engine.execute(update)

    string_column.alter(name='instance_type_id_str')
    integer_column.alter(name='instance_type_id')
    string_column.drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)

    integer_column = instances.c.instance_type_id
    string_column = Column('instance_type_id_str',
                           String(length=255, convert_unicode=False,
                                  assert_unicode=None, unicode_error=None,
                                  _warn_on_bytestring=False),
                           nullable=True)

    types = {}
    for instance in migrate_engine.execute(instances.select()):
        if instance.instance_type_id is None:
            types[instance.id] = None
        else:
            types[instance.id] = str(instance.instance_type_id)

    string_column.create(instances)
    for instance_id, instance_type_id in types.iteritems():
        update = instances.update().\
                where(instances.c.id == instance_id).\
                values(instance_type_id_str=instance_type_id)
        migrate_engine.execute(update)

    integer_column.alter(name='instance_type_id_int')
    string_column.alter(name='instance_type_id')
    integer_column.drop()
