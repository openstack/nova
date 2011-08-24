# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import os
import sys

from nova import flags

import sqlalchemy
from migrate.versioning import api as versioning_api

try:
    from migrate.versioning import exceptions as versioning_exceptions
except ImportError:
    try:
        # python-migration changed location of exceptions after 1.6.3
        # See LP Bug #717467
        from migrate import exceptions as versioning_exceptions
    except ImportError:
        sys.exit(_("python-migrate is not installed. Exiting."))

FLAGS = flags.FLAGS


def db_sync(version=None):
    db_version()
    repo_path = _find_migrate_repo()
    return versioning_api.upgrade(FLAGS.sql_connection, repo_path, version)


def db_version():
    repo_path = _find_migrate_repo()
    try:
        return versioning_api.db_version(FLAGS.sql_connection, repo_path)
    except versioning_exceptions.DatabaseNotControlledError:
        # If we aren't version controlled we may already have the database
        # in the state from before we started version control, check for that
        # and set up version_control appropriately
        meta = sqlalchemy.MetaData()
        engine = sqlalchemy.create_engine(FLAGS.sql_connection, echo=False)
        meta.reflect(bind=engine)
        try:
            for table in ('auth_tokens', 'zones', 'export_devices',
                          'fixed_ips', 'floating_ips', 'instances',
                          'key_pairs', 'networks', 'projects', 'quotas',
                          'security_group_instance_association',
                          'security_group_rules', 'security_groups',
                          'services', 'migrations',
                          'users', 'user_project_association',
                          'user_project_role_association',
                          'user_role_association',
                          'virtual_storage_arrays',
                          'volumes', 'volume_metadata',
                          'volume_types', 'volume_type_extra_specs'):
                assert table in meta.tables
            return db_version_control(1)
        except AssertionError:
            return db_version_control(0)


def db_version_control(version=None):
    repo_path = _find_migrate_repo()
    versioning_api.version_control(FLAGS.sql_connection, repo_path, version)
    return version


def _find_migrate_repo():
    """Get the path for the migrate repository."""
    path = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                        'migrate_repo')
    assert os.path.exists(path)
    return path
