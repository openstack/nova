# Copyright 2011 OpenStack LLC.
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

from sqlalchemy import MetaData, Table
from migrate import ForeignKeyConstraint

from nova import log as logging

meta = MetaData()


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine
    dialect = migrate_engine.url.get_dialect().name
    if dialect.startswith('sqlite'):
        return

    networks = Table('networks', meta, autoload=True)
    vifs = Table('virtual_interfaces', meta, autoload=True)

    try:
        fkey_name = list(vifs.c.network_id.foreign_keys)[0].constraint.name
        ForeignKeyConstraint(columns=[vifs.c.network_id],
                             refcolumns=[networks.c.id],
                             name=fkey_name).drop()

    except Exception:
        logging.error(_("foreign key constraint couldn't be removed"))
        raise


def downgrade(migrate_engine):
    # Operations to reverse the above upgrade go here.
    meta.bind = migrate_engine
    dialect = migrate_engine.url.get_dialect().name
    if dialect.startswith('sqlite'):
        return

    networks = Table('networks', meta, autoload=True)
    vifs = Table('virtual_interfaces', meta, autoload=True)

    try:
        ForeignKeyConstraint(columns=[vifs.c.network_id],
                             refcolumns=[networks.c.id]).create()
    except Exception:
        logging.error(_("foreign key constraint couldn't be added"))
        raise
