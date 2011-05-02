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

"""Database setup and migration commands."""

from nova import flags
from nova import utils


FLAGS = flags.FLAGS
flags.DECLARE('db_backend', 'nova.db.api')


IMPL = utils.LazyPluggable(FLAGS['db_backend'],
                           sqlalchemy='nova.db.sqlalchemy.migration')


def db_sync(version=None):
    """Migrate the database to `version` or the most recent version."""
    return IMPL.db_sync(version=version)


def db_version():
    """Display the current database version."""
    return IMPL.db_version()
