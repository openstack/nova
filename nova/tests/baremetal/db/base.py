# Copyright (c) 2012 NTT DOCOMO, INC.
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

"""Bare-metal DB test base class."""

from nova import context as nova_context
from nova.openstack.common import cfg
from nova import test
from nova.virt.baremetal.db import migration as bm_migration
from nova.virt.baremetal.db.sqlalchemy import session as bm_session

_DB = None

CONF = cfg.CONF
CONF.import_opt('baremetal_sql_connection',
                'nova.virt.baremetal.db.sqlalchemy.session')


def _reset_bmdb():
    global _DB
    engine = bm_session.get_engine()
    engine.dispose()
    conn = engine.connect()
    if _DB is None:
        if bm_migration.db_version() > bm_migration.INIT_VERSION:
            return
        bm_migration.db_sync()
        _DB = "".join(line for line in conn.connection.iterdump())
    else:
        conn.connection.executescript(_DB)


class BMDBTestCase(test.TestCase):

    def setUp(self):
        super(BMDBTestCase, self).setUp()
        self.flags(baremetal_sql_connection='sqlite:///:memory:')
        _reset_bmdb()
        self.context = nova_context.get_admin_context()
