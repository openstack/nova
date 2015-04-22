# Copyright 2014 IBM Corp.
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

from migrate import UniqueConstraint
from oslo_log import log as logging
from sqlalchemy import MetaData
from sqlalchemy.sql import null

from nova import exception
from nova.i18n import _

LOG = logging.getLogger(__name__)

UC_NAME = 'uniq_instances0uuid'


def scan_for_null_records(table, col_name, check_fkeys):
    """Queries the table looking for NULL instances of the given column.

    :param col_name: The name of the column to look for in the table.
    :param check_fkeys: If True, check the table for foreign keys back to the
        instances table and if not found, return.
    :raises: exception.ValidationError: If any records are found.
    """
    if col_name in table.columns:
        # NOTE(mriedem): filter out tables that don't have a foreign key back
        # to the instances table since they could have stale data even if
        # instances.uuid wasn't NULL.
        if check_fkeys:
            fkey_found = False
            fkeys = table.c[col_name].foreign_keys or []
            for fkey in fkeys:
                if fkey.column.table.name == 'instances':
                    fkey_found = True

            if not fkey_found:
                return

        records = len(list(
            table.select().where(table.c[col_name] == null()).execute()
        ))
        if records:
            msg = _("There are %(records)d records in the "
                    "'%(table_name)s' table where the uuid or "
                    "instance_uuid column is NULL. These must be "
                    "manually cleaned up before the migration will pass. "
                    "Consider running the "
                    "'nova-manage db null_instance_uuid_scan' command.") % (
                    {'records': records, 'table_name': table.name})
            raise exception.ValidationError(detail=msg)


def process_null_records(meta, scan=True):
    """Scans the database for null instance_uuid records for processing.

    :param meta: sqlalchemy.MetaData object, assumes tables are reflected.
    :param scan: If True, does a query and fails the migration if NULL instance
                 uuid entries found. If False, makes instances.uuid
                 non-nullable.
    """
    if scan:
        for table in reversed(meta.sorted_tables):
            # NOTE(mriedem): There is a periodic task in the network manager
            # that calls nova.db.api.fixed_ip_disassociate_all_by_timeout which
            # will set fixed_ips.instance_uuid to None by design, so we have to
            # skip the fixed_ips table otherwise we'll wipeout the pool of
            # fixed IPs.
            if table.name not in ('fixed_ips', 'shadow_fixed_ips'):
                scan_for_null_records(table, 'instance_uuid', check_fkeys=True)

    for table_name in ('instances', 'shadow_instances'):
        table = meta.tables[table_name]
        if scan:
            scan_for_null_records(table, 'uuid', check_fkeys=False)
        else:
            # The record is gone so make the uuid column non-nullable.
            table.columns.uuid.alter(nullable=False)


def upgrade(migrate_engine):
    # NOTE(mriedem): We're going to load up all of the tables so we can find
    # any with an instance_uuid column since those may be foreign keys back
    # to the instances table and we want to cleanup those records first. We
    # have to do this explicitly because the foreign keys in nova aren't
    # defined with cascading deletes.
    meta = MetaData(migrate_engine)
    meta.reflect(migrate_engine)
    # Scan the database first and fail if any NULL records found.
    process_null_records(meta, scan=True)
    # Now run the alter statements.
    process_null_records(meta, scan=False)
    # Create a unique constraint on instances.uuid for foreign keys.
    instances = meta.tables['instances']
    UniqueConstraint('uuid', table=instances, name=UC_NAME).create()

    # NOTE(mriedem): We now have a unique index on instances.uuid from the
    # 216_havana migration and a unique constraint on the same column, which
    # is redundant but should not be a big performance penalty. We should
    # clean this up in a later (separate) migration since it involves dropping
    # any ForeignKeys on the instances.uuid column due to some index rename
    # issues in older versions of MySQL. That is beyond the scope of this
    # migration.
