# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import migrate
import migrate.changeset
import sqlalchemy

from nova import log as logging


LOG = logging.getLogger(__name__)

meta = sqlalchemy.MetaData()


def _get_table():
    return sqlalchemy.Table('instance_types', meta, autoload=True)


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    instance_types = _get_table()

    string_column = sqlalchemy.Column('flavorid_str', sqlalchemy.String(255))

    string_column.create(instance_types)

    try:
        # NOTE(bcwaldon): This catches a bug with python-migrate
        # failing to add the unique constraint
        try:
            migrate.UniqueConstraint(string_column).create()
        except migrate.changeset.NotSupportedError:
            LOG.error("Failed to add unique constraint on flavorid")
            pass

        # NOTE(bcwaldon): this is a hack to preserve uniqueness constraint
        # on existing 'name' column
        try:
            migrate.UniqueConstraint(instance_types.c.name).create()
        except Exception:
            pass

        integer_column = instance_types.c.flavorid

        instance_type_rows = list(instance_types.select().execute())
        for instance_type in instance_type_rows:
            flavorid_int = instance_type.flavorid
            instance_types.update()\
                          .where(integer_column == flavorid_int)\
                          .values(flavorid_str=str(flavorid_int))\
                          .execute()
    except Exception:
        string_column.drop()
        raise

    integer_column.alter(name='flavorid_int')
    string_column.alter(name='flavorid')
    integer_column.drop()


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    instance_types = _get_table()

    integer_column = sqlalchemy.Column('flavorid_int',
                                       sqlalchemy.Integer())

    integer_column.create(instance_types)

    try:
        # NOTE(bcwaldon): This catches a bug with python-migrate
        # failing to add the unique constraint
        try:
            migrate.UniqueConstraint(integer_column).create()
        except migrate.changeset.NotSupportedError:
            LOG.info("Failed to add unique constraint on flavorid")
            pass

        string_column = instance_types.c.flavorid

        instance_types_rows = list(instance_types.select().execute())
        for instance_type in instance_types_rows:
            flavorid_str = instance_type.flavorid
            try:
                flavorid_int = int(instance_type.flavorid)
            except ValueError:
                msg = _('Could not cast flavorid to integer: %s. '
                        'Set flavorid to an integer-like string to downgrade.')
                LOG.error(msg % instance_type.flavorid)
                raise

            instance_types.update()\
                          .where(string_column == flavorid_str)\
                          .values(flavorid_int=flavorid_int)\
                          .execute()
    except Exception:
        integer_column.drop()
        raise

    string_column.alter(name='flavorid_str')
    integer_column.alter(name='flavorid')
    string_column.drop()
