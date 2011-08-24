# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from sqlalchemy import Boolean, Column, DateTime, Integer
from sqlalchemy import MetaData, String, Table

from nova import utils

meta = MetaData()

resources = [
    'instances',
    'cores',
    'volumes',
    'gigabytes',
    'floating_ips',
    'metadata_items',
]


def old_style_quotas_table(name):
    return Table(name, meta,
                 Column('id', Integer(), primary_key=True),
                 Column('created_at', DateTime(),
                        default=utils.utcnow),
                 Column('updated_at', DateTime(),
                        onupdate=utils.utcnow),
                 Column('deleted_at', DateTime()),
                 Column('deleted', Boolean(), default=False),
                 Column('project_id',
                        String(length=255, convert_unicode=False,
                               assert_unicode=None, unicode_error=None,
                               _warn_on_bytestring=False)),
                 Column('instances', Integer()),
                 Column('cores', Integer()),
                 Column('volumes', Integer()),
                 Column('gigabytes', Integer()),
                 Column('floating_ips', Integer()),
                 Column('metadata_items', Integer()),
                )


def new_style_quotas_table(name):
    return Table(name, meta,
                 Column('id', Integer(), primary_key=True),
                 Column('created_at', DateTime(),
                        default=utils.utcnow),
                 Column('updated_at', DateTime(),
                        onupdate=utils.utcnow),
                 Column('deleted_at', DateTime()),
                 Column('deleted', Boolean(), default=False),
                 Column('project_id',
                        String(length=255, convert_unicode=False,
                               assert_unicode=None, unicode_error=None,
                               _warn_on_bytestring=False)),
                 Column('resource',
                        String(length=255, convert_unicode=False,
                               assert_unicode=None, unicode_error=None,
                               _warn_on_bytestring=False),
                        nullable=False),
                 Column('hard_limit', Integer(), nullable=True),
                )


def quotas_table(migrate_engine, name='quotas'):
    return Table(name, meta, autoload=True, autoload_with=migrate_engine)


def _assert_no_duplicate_project_ids(quotas):
    project_ids = set()
    message = ('There are multiple active quotas for project "%s" '
               '(among others, possibly). '
               'Please resolve all ambiguous quotas before '
               'reattempting the migration.')
    for quota in quotas:
        assert quota.project_id not in project_ids, message % quota.project_id
        project_ids.add(quota.project_id)


def assert_old_quotas_have_no_active_duplicates(migrate_engine, quotas):
    """Ensure that there are no duplicate non-deleted quota entries."""
    select = quotas.select().where(quotas.c.deleted == False)
    results = migrate_engine.execute(select)
    _assert_no_duplicate_project_ids(list(results))


def assert_new_quotas_have_no_active_duplicates(migrate_engine, quotas):
    """Ensure that there are no duplicate non-deleted quota entries."""
    for resource in resources:
        select = quotas.select().\
                where(quotas.c.deleted == False).\
                where(quotas.c.resource == resource)
        results = migrate_engine.execute(select)
        _assert_no_duplicate_project_ids(list(results))


def convert_forward(migrate_engine, old_quotas, new_quotas):
    quotas = list(migrate_engine.execute(old_quotas.select()))
    for quota in quotas:
        for resource in resources:
            hard_limit = getattr(quota, resource)
            if hard_limit is None:
                continue
            insert = new_quotas.insert().values(
                created_at=quota.created_at,
                updated_at=quota.updated_at,
                deleted_at=quota.deleted_at,
                deleted=quota.deleted,
                project_id=quota.project_id,
                resource=resource,
                hard_limit=hard_limit)
            migrate_engine.execute(insert)


def earliest(date1, date2):
    if date1 is None and date2 is None:
        return None
    if date1 is None:
        return date2
    if date2 is None:
        return date1
    if date1 < date2:
        return date1
    return date2


def latest(date1, date2):
    if date1 is None and date2 is None:
        return None
    if date1 is None:
        return date2
    if date2 is None:
        return date1
    if date1 > date2:
        return date1
    return date2


def convert_backward(migrate_engine, old_quotas, new_quotas):
    quotas = {}
    for quota in migrate_engine.execute(new_quotas.select()):
        if (quota.resource not in resources
            or quota.hard_limit is None or quota.deleted):
            continue
        if not quota.project_id in quotas:
            quotas[quota.project_id] = {
                'project_id': quota.project_id,
                'created_at': quota.created_at,
                'updated_at': quota.updated_at,
                quota.resource: quota.hard_limit,
            }
        else:
            quotas[quota.project_id]['created_at'] = earliest(
                quota.created_at, quotas[quota.project_id]['created_at'])
            quotas[quota.project_id]['updated_at'] = latest(
                quota.updated_at, quotas[quota.project_id]['updated_at'])
            quotas[quota.project_id][quota.resource] = quota.hard_limit

    for quota in quotas.itervalues():
        insert = old_quotas.insert().values(**quota)
        migrate_engine.execute(insert)


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine

    old_quotas = quotas_table(migrate_engine)
    assert_old_quotas_have_no_active_duplicates(migrate_engine, old_quotas)

    new_quotas = new_style_quotas_table('quotas_new')
    new_quotas.create()
    convert_forward(migrate_engine, old_quotas, new_quotas)
    old_quotas.drop()

    # clear metadata to work around this:
    # http://code.google.com/p/sqlalchemy-migrate/issues/detail?id=128
    meta.clear()
    new_quotas = quotas_table(migrate_engine, 'quotas_new')
    new_quotas.rename('quotas')


def downgrade(migrate_engine):
    # Operations to reverse the above upgrade go here.
    meta.bind = migrate_engine

    new_quotas = quotas_table(migrate_engine)
    assert_new_quotas_have_no_active_duplicates(migrate_engine, new_quotas)

    old_quotas = old_style_quotas_table('quotas_old')
    old_quotas.create()
    convert_backward(migrate_engine, old_quotas, new_quotas)
    new_quotas.drop()

    # clear metadata to work around this:
    # http://code.google.com/p/sqlalchemy-migrate/issues/detail?id=128
    meta.clear()
    old_quotas = quotas_table(migrate_engine, 'quotas_old')
    old_quotas.rename('quotas')
