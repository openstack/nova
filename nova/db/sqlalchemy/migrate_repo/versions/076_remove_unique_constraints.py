# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) OpenStack, LLC
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

from sqlalchemy import MetaData, Table
from migrate.changeset.constraint import UniqueConstraint


def _get_constraint_names(engine_name):

    # NOTE(vish): These constraint names may be dependent on the backend, but
    #             there doesn't seem to be we a way to determine the proper
    #             name for existing constraints. These names are correct for
    #             mysql and postgres.
    if engine_name == "mysql":
        return {
            "instance_types_name": ("name", "instance_types_name_key"),
            "instance_types_flavorid": "instance_types_flavorid_str_key",
            "volume_types_name": "name",
        }
    else:
        return {
            "instance_types_name": ("instance_types_name_key",),
            "instance_types_flavorid": "instance_types_flavorid_str_key",
            "volume_types_name": "volume_types_name_key",
        }


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    c_names = _get_constraint_names(migrate_engine.name)

    table = Table('instance_types', meta, autoload=True)
    for constraint_name in c_names['instance_types_name']:
        cons = UniqueConstraint('name',
                                name=constraint_name,
                                table=table)
        cons.drop()
    cons = UniqueConstraint('flavorid',
                            name=c_names['instance_types_flavorid'],
                            table=table)
    cons.drop()
    table = Table('volume_types', meta, autoload=True)
    cons = UniqueConstraint('name',
                            name=c_names['volume_types_name'],
                            table=table)
    cons.drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    c_names = _get_constraint_names(migrate_engine.name)

    table = Table('instance_types', meta, autoload=True)
    for constraint_name in c_names['instance_types_name']:
        cons = UniqueConstraint('name',
                                name=constraint_name,
                                table=table)
        cons.create()
    table = Table('instance_types', meta, autoload=True)
    cons = UniqueConstraint('flavorid',
                            name=c_names['instance_types_flavorid'],
                            table=table)
    cons.create()
    table = Table('volume_types', meta, autoload=True)
    cons = UniqueConstraint('name',
                            name=c_names['volume_types_name'],
                            table=table)
    cons.create()
