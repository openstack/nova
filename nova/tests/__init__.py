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
.. moduleauthor:: Jesse Andrews <jesse@ansolabs.com>
.. moduleauthor:: Devin Carlen <devin.carlen@gmail.com>
.. moduleauthor:: Vishvananda Ishaya <vishvananda@gmail.com>
.. moduleauthor:: Joshua McKenty <joshua@cognition.ca>
.. moduleauthor:: Manish Singh <yosh@gimp.org>
.. moduleauthor:: Andy Smith <andy@anarkystic.com>
"""

# See http://code.google.com/p/python-nose/issues/detail?id=373
# The code below enables nosetests to work with i18n _() blocks
import __builtin__
setattr(__builtin__, '_', lambda x: x)
import os
import shutil

from nova.db.sqlalchemy.session import get_engine
from nova import flags

FLAGS = flags.FLAGS

_DB = None


def reset_db():
    if FLAGS.sql_connection == "sqlite://":
        engine = get_engine()
        engine.dispose()
        conn = engine.connect()
        if _DB:
            conn.connection.executescript(_DB)
    else:
        shutil.copyfile(os.path.join(FLAGS.state_path, FLAGS.sqlite_clean_db),
                        os.path.join(FLAGS.state_path, FLAGS.sqlite_db))


def setup():
    import mox  # Fail fast if you don't have mox. Workaround for bug 810424

    from nova import rpc  # Register rpc_backend before fake_flags sets it
    FLAGS.register_opts(rpc.rpc_opts)

    from nova import context
    from nova import db
    from nova.db import migration
    from nova.network import manager as network_manager
    from nova.tests import fake_flags

    if FLAGS.sql_connection == "sqlite://":
        if migration.db_version() > migration.INIT_VERSION:
            return
    else:
        testdb = os.path.join(FLAGS.state_path, FLAGS.sqlite_db)
        if os.path.exists(testdb):
            return
    migration.db_sync()
    ctxt = context.get_admin_context()
    network = network_manager.VlanManager()
    bridge_interface = FLAGS.flat_interface or FLAGS.vlan_interface
    network.create_networks(ctxt,
                            label='test',
                            cidr=FLAGS.fixed_range,
                            multi_host=FLAGS.multi_host,
                            num_networks=FLAGS.num_networks,
                            network_size=FLAGS.network_size,
                            cidr_v6=FLAGS.fixed_range_v6,
                            gateway=FLAGS.gateway,
                            gateway_v6=FLAGS.gateway_v6,
                            bridge=FLAGS.flat_network_bridge,
                            bridge_interface=bridge_interface,
                            vpn_start=FLAGS.vpn_start,
                            vlan_start=FLAGS.vlan_start,
                            dns1=FLAGS.flat_network_dns)
    for net in db.network_get_all(ctxt):
        network.set_network_host(ctxt, net)

    if FLAGS.sql_connection == "sqlite://":
        global _DB
        engine = get_engine()
        conn = engine.connect()
        _DB = "".join(line for line in conn.connection.iterdump())
    else:
        cleandb = os.path.join(FLAGS.state_path, FLAGS.sqlite_clean_db)
        shutil.copyfile(testdb, cleandb)
