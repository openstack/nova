# Copyright 2012 OpenStack Foundation
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

from sqlalchemy import and_, Index, String, Column, MetaData, Table
from sqlalchemy.sql.expression import select, update


def _drop_index(engine, table, idx_name):
    """Drop index from DB and remove index from SQLAlchemy table metadata.

    idx.drop() in SQLAlchemy will issue a DROP INDEX statement to the DB but
    WILL NOT update the table metadata to remove the `Index` object.

    This can cause subsequent drop column calls on a related column to fail
    because `drop_column` will see an `Index` object that isn't there, thus
    issuing an erroneous second DROP INDEX call.

    The solution is to update the table metadata to reflect the now dropped
    column.
    """
    for idx in getattr(table, 'indexes'):
        if idx.name == idx_name:
            break
    else:
        raise Exception("Index '%s' not found!" % idx_name)

    idx.drop(engine)
    table.indexes.remove(idx)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)
    migrations = Table('migrations', meta, autoload=True)

    # drop old index:
    i = _old_index(migrations)
    i.drop(migrate_engine)

    # add columns.  a node is the same as a compute node's
    # hypervisor hostname:
    source_node = Column('source_node', String(length=255))
    migrations.create_column(source_node)

    dest_node = Column('dest_node', String(length=255))
    migrations.create_column(dest_node)

    # map compute hosts => list of compute nodes
    nodemap = _map_nodes(meta)

    # update migration and instance records with nodes:
    _update_nodes(nodemap, instances, migrations)

    # add new index:
    migrations = Table('migrations', meta, autoload=True)
    _add_new_index(migrations, migrate_engine)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    migrations = Table('migrations', meta, autoload=True)

    # drop new index:
    _drop_index(migrate_engine, migrations,
                'migrations_by_host_nodes_and_status_idx')

    # drop new columns:
    migrations.drop_column('source_node')

    migrations.drop_column('dest_node')

    # re-add old index:
    i = _old_index(migrations)
    i.create(migrate_engine)


def _map_nodes(meta):
    """Map host to compute node(s) for the purpose of determining which hosts
    are single vs multi-node.
    """

    services = Table('services', meta, autoload=True)
    c_nodes = Table('compute_nodes', meta, autoload=True)

    q = select([services.c.host, c_nodes.c.hypervisor_hostname],

               whereclause=and_(c_nodes.c.deleted == False,
                                services.c.deleted == False),

               from_obj=c_nodes.join(services,
                                     c_nodes.c.service_id == services.c.id)
    )

    nodemap = {}

    for (host, node) in q.execute():
        nodes = nodemap.setdefault(host, [])
        nodes.append(node)

    return nodemap


def _add_new_index(migrations, migrate_engine):
    if migrate_engine.name == "mysql":
        # mysql-specific index by leftmost 100 chars.  (mysql gets angry if the
        # index key length is too long.)
        sql = ("create index migrations_by_host_nodes_and_status_idx ON "
               "migrations (deleted, source_compute(100), dest_compute(100), "
               "source_node(100), dest_node(100), status)")
        migrate_engine.execute(sql)

    else:
        i = Index('migrations_by_host_nodes_and_status_idx',
                  migrations.c.deleted, migrations.c.source_compute,
                  migrations.c.dest_compute, migrations.c.source_node,
                  migrations.c.dest_node, migrations.c.status)
        i.create(migrate_engine)


def _old_index(migrations):
    i = Index('migrations_by_host_and_status_idx', migrations.c.deleted,
              migrations.c.source_compute, migrations.c.dest_compute,
              migrations.c.status)
    return i


def _update_nodes(nodemap, instances, migrations):
    """For each migration and matching instance record, update the node columns
    if the referenced host is single-node.

    Skip updates for multi-node hosts.  In that case, there's no way to
    determine which node on a host the record should be associated with.
    """
    q = select([migrations.c.id, migrations.c.source_compute,
               migrations.c.dest_compute, instances.c.uuid, instances.c.host,
               instances.c.node],

               whereclause=and_(migrations.c.source_compute != None,
                                migrations.c.dest_compute != None,
                                instances.c.deleted == False,
                                migrations.c.status != 'reverted',
                                migrations.c.status != 'error'),

               from_obj=migrations.join(instances,
                   migrations.c.instance_uuid == instances.c.uuid)
    )

    result = q.execute()
    for migration_id, src, dest, uuid, instance_host, instance_node in result:

        values = {}

        nodes = nodemap.get(src, [])

        if len(nodes) == 1:
            # the source host is a single-node, safe to update node
            node = nodes[0]
            values['source_node'] = node

            if src == instance_host and node != instance_node:
                update(instances).where(instances.c.uuid == uuid).\
                        values(node=node)

        nodes = nodemap.get(dest, [])
        if len(nodes) == 1:
            # the dest host is a single-node, safe to update node
            node = nodes[0]
            values['dest_node'] = node

            if dest == instance_host and node != instance_node:
                update(instances).where(instances.c.uuid == uuid).\
                        values(node=node)

        if values:
            q = update(migrations,
                   values=values,
                   whereclause=migrations.c.id == migration_id)
            q.execute()
