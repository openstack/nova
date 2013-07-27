# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from migrate.changeset import UniqueConstraint
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.sql.expression import select

from nova.cells import rpc_driver
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def get_tables(engine, *names):
    meta = MetaData(bind=engine)
    return [Table(name, meta, autoload=True) for name in names]


def create_column(table, name, type_):
    column = Column(name, type_)
    column.create(table)


def get_column(table, name):
    return getattr(table.c, name)


def drop_column(table, name):
    column = get_column(table, name)
    column.drop()


def restore_unique_constraint(table):
    # NOTE(Vek): So, sqlite doesn't really support dropping columns,
    #            and so it gets implemented by dropping and recreating
    #            the table...which of course means we completely lose
    #            the unique constraint.  We re-create it here to work
    #            around this issue.
    uc_name = 'uniq_cell_name0deleted'
    columns = ('name', 'deleted')
    uc = UniqueConstraint(*columns, table=table, name=uc_name)
    uc.create()


def upgrade(migrate_engine):
    tables = get_tables(migrate_engine, 'cells', 'shadow_cells')

    for table in tables:
        create_column(table, 'transport_url', String(255))

        upgrade_cell_data(table)

        drop_column(table, 'username')
        drop_column(table, 'password')
        drop_column(table, 'rpc_host')
        drop_column(table, 'rpc_port')
        drop_column(table, 'rpc_virtual_host')

        table.c.transport_url.alter(nullable=False)

    if migrate_engine.name == "sqlite":
        restore_unique_constraint(tables[0])


def downgrade(migrate_engine):
    tables = get_tables(migrate_engine, 'cells', 'shadow_cells')

    for table in tables:
        create_column(table, 'username', String(255))
        create_column(table, 'password', String(255))
        create_column(table, 'rpc_host', String(255))
        create_column(table, 'rpc_port', Integer())
        create_column(table, 'rpc_virtual_host', String(255))

        downgrade_cell_data(table)

        drop_column(table, 'transport_url')

    if migrate_engine.name == "sqlite":
        restore_unique_constraint(tables[0])


def upgrade_cell_data(table):
    # List of database columns
    columns = ['id', 'username', 'password', 'rpc_host', 'rpc_port',
               'rpc_virtual_host']

    # List of names to give the data from those columns; the fields
    # are chosen so that the dictionary matches that expected by
    # unparse_transport_url()
    fields = ['id', 'username', 'password', 'hostname', 'port', 'virtual_host']

    query = select([get_column(table, c) for c in columns])
    for row in [dict(zip(fields, result)) for result in query.execute()]:
        # Compute the transport URL
        url = rpc_driver.unparse_transport_url(row)

        # Store the transport URL in the database
        table.update().where(table.c.id == row['id']).\
            values(transport_url=url).execute()


field_map = {
    'hostname': 'rpc_host',
    'port': 'rpc_port',
    'virtual_host': 'rpc_virtual_host',
}


def downgrade_cell_data(table):
    columns = ['id', 'name', 'transport_url']
    query = select([get_column(table, c) for c in columns])
    for row in [dict(zip(columns, result)) for result in query.execute()]:
        # Disassemble the transport URL
        transport_data = {}
        try:
            transport = rpc_driver.parse_transport_url(row['transport_url'])

            for key, value in transport.items():
                if not value:
                    # Ignore empty values
                    continue
                transport_data[field_map.get(key, key)] = value
        except ValueError as exc:
            # We failed to parse the transport URL, so don't set up
            # any transport data
            LOG.warning(_('Failed to downgrade cell %(name)s: %(error)s') %
                        dict(name=row['name'], error=str(exc)))

        if transport_data:
            table.update().where(table.c.id == row['id']).\
                values(**transport_data).execute()
