# Copyright (c) 2012 NTT DOCOMO, INC.
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

"""Session Handling for SQLAlchemy backend."""

from oslo.config import cfg

from nova.openstack.common.db.sqlalchemy import session as db_session
from nova import paths

opts = [
    cfg.StrOpt('sql_connection',
               default=('sqlite:///' +
                        paths.state_path_def('baremetal_nova.sqlite')),
               help='The SQLAlchemy connection string used to connect to the '
                    'bare-metal database'),
    ]

baremetal_group = cfg.OptGroup(name='baremetal',
                               title='Baremetal Options')

CONF = cfg.CONF
CONF.register_group(baremetal_group)
CONF.register_opts(opts, baremetal_group)


_FACADE = None


def _create_facade_lazily():
    global _FACADE

    if _FACADE is None:
        _FACADE = db_session.EngineFacade(CONF.baremetal.sql_connection,
                                          **dict(CONF.database.iteritems()))

    return _FACADE


def get_session(autocommit=True, expire_on_commit=False):
    """Return a SQLAlchemy session."""

    facade = _create_facade_lazily()
    return facade.get_session(autocommit=autocommit,
                              expire_on_commit=expire_on_commit)


def get_engine():
    """Return a SQLAlchemy engine."""

    facade = _create_facade_lazily()
    return facade.get_engine()
