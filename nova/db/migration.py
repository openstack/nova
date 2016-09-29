# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Database setup and migration commands."""

from nova.db.sqlalchemy import migration

IMPL = migration


def db_sync(version=None, database='main', context=None):
    """Migrate the database to `version` or the most recent version."""
    return IMPL.db_sync(version=version, database=database, context=context)


def db_version(database='main', context=None):
    """Display the current database version."""
    return IMPL.db_version(database=database, context=context)


def db_initial_version(database='main'):
    """The starting version for the database."""
    return IMPL.db_initial_version(database=database)


def db_null_instance_uuid_scan(delete=False):
    """Utility for scanning the database to look for NULL instance uuid rows.

    Scans the backing nova database to look for table entries where
    instances.uuid or instance_uuid columns are NULL (except for the
    fixed_ips table since that can contain NULL instance_uuid entries by
    design). Dumps the tables that have NULL instance_uuid entries or
    optionally deletes them based on usage.

    This tool is meant to be used in conjunction with the 267 database
    migration script to detect and optionally cleanup NULL instance_uuid
    records.

    :param delete: If true, delete NULL instance_uuid records found, else
                   just query to see if they exist for reporting.
    :returns: dict of table name to number of hits for NULL instance_uuid rows.
    """
    return IMPL.db_null_instance_uuid_scan(delete=delete)
