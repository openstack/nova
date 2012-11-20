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

"""
:mod:`nova.tests` -- Nova Unittests
=====================================================

.. automodule:: nova.tests
   :platform: Unix
"""

# See http://code.google.com/p/python-nose/issues/detail?id=373
# The code below enables nosetests to work with i18n _() blocks
import __builtin__
setattr(__builtin__, '_', lambda x: x)
import os
import shutil

from nova import config
from nova.db.sqlalchemy.session import get_engine
from nova.openstack.common import cfg
from nova.openstack.common import log as logging

import eventlet


eventlet.monkey_patch(os=False)

CONF = cfg.CONF
CONF.set_override('use_stderr', False)

logging.setup('nova')

_DB = None


def reset_db():
    if CONF.sql_connection == "sqlite://":
        engine = get_engine()
        engine.dispose()
        conn = engine.connect()
        if _DB:
            conn.connection.executescript(_DB)
        else:
            setup()
    else:
        shutil.copyfile(os.path.join(CONF.state_path, CONF.sqlite_clean_db),
                        os.path.join(CONF.state_path, CONF.sqlite_db))


def setup():
    import mox  # Fail fast if you don't have mox. Workaround for bug 810424

    from nova import context
    from nova import db
    from nova.db import migration
    from nova.network import manager as network_manager
    from nova.tests import fake_flags
    fake_flags.set_defaults(CONF)

    if CONF.sql_connection == "sqlite://":
        if migration.db_version() > migration.INIT_VERSION:
            return
    else:
        testdb = os.path.join(CONF.state_path, CONF.sqlite_db)
        if os.path.exists(testdb):
            return
    migration.db_sync()
    ctxt = context.get_admin_context()
    network = network_manager.VlanManager()
    bridge_interface = CONF.flat_interface or CONF.vlan_interface
    network.create_networks(ctxt,
                            label='test',
                            cidr=CONF.fixed_range,
                            multi_host=CONF.multi_host,
                            num_networks=CONF.num_networks,
                            network_size=CONF.network_size,
                            cidr_v6=CONF.fixed_range_v6,
                            gateway=CONF.gateway,
                            gateway_v6=CONF.gateway_v6,
                            bridge=CONF.flat_network_bridge,
                            bridge_interface=bridge_interface,
                            vpn_start=CONF.vpn_start,
                            vlan_start=CONF.vlan_start,
                            dns1=CONF.flat_network_dns)
    for net in db.network_get_all(ctxt):
        network.set_network_host(ctxt, net)

    if CONF.sql_connection == "sqlite://":
        global _DB
        engine = get_engine()
        conn = engine.connect()
        _DB = "".join(line for line in conn.connection.iterdump())
    else:
        cleandb = os.path.join(CONF.state_path, CONF.sqlite_clean_db)
        shutil.copyfile(testdb, cleandb)
