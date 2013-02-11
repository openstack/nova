#!/usr/bin/env python

import eventlet
eventlet.monkey_patch()

import sys
sys.path.append(".")

import gettext
gettext.install(None)

import logging

logging.basicConfig()
root = logging.getLogger()
root.setLevel(logging.DEBUG)

import sqlalchemy

from nova import config
from nova import context
from nova.openstack.common import cfg
from nova.openstack.common import eventlet_backdoor
from nova import db
from nova.openstack.common.db.sqlalchemy import session


# Just to get CONF values
from nova.db.mysqldb import connection
from nova.db.mysqldb import api

CONF = cfg.CONF

# hack a config file arg onto argv
sys.argv.insert(1, "--config-file=/etc/nova/nova.conf")
config.parse_args(sys.argv)

CONF.sql_max_pool_size = 40
CONF.sql_max_overflow = 100
CONF.backdoor_port = 0
#CONF.sql_connection_debug = 100
#CONF.dbapi_tpool_enable = True
#CONF.use_eventlet_tpool = True
#CONF.sql_connection_trace = True

sql_connection = CONF.sql_connection
connection_dict = sqlalchemy.engine.url.make_url(sql_connection)

CONF.set_override('password', connection_dict.password or '', group='mysqldb')
CONF.set_override('database', connection_dict.database, group='mysqldb')
CONF.set_override('username', connection_dict.username, group='mysqldb')
CONF.set_override('hostname', connection_dict.host, group='mysqldb')
if connection_dict.port is not None:
    CONF.set_override('port', connection_dict.port, group='mysqldb')
CONF.set_override('use_tpool', True, group='mysqldb')
CONF.db_backend='mysqldb'

eventlet_backdoor.initialize_if_enabled()

# try to simulate innodb lock on bw:
ctxt = context.get_admin_context()

import uuid

def gen_uuid():
    u = str(uuid.uuid4())
    return 'comstud0' + u[8:]

def gen_mac():
    u = str(uuid.uuid4()).replace('-', '')
    return ':'.join([u[i * 2:i * 2 + 2] for i in xrange(6)])

# generate a pile of instance uuids:
uuids = [gen_uuid() for i in range(20)]

# generate a pile of fake macs:
macs = [gen_mac() for i in range(20)]

# use a single start time to increase deadlock possibility
import datetime
start_time = datetime.datetime.utcnow()

import random
random.seed()

def bw_updater():
    for x in xrange(2000):
        # pick random uuid
        x = random.randint(0,len(uuids) - 1)
        uuid = uuids[x]

        # pick random mac
        x = random.randint(0, len(macs) - 1)
        mac = macs[x]
        while True:
            try:
                db.bw_usage_update(ctxt, uuid, mac, start_time, 1, 2, 3, 4)
                break
            except Exception:
                raise
                continue
        sys.stdout.write(".")
        sys.stdout.flush()


pool = eventlet.GreenPool()

for x in xrange(20):
    pool.spawn(session.get_session)
pool.waitall()

eventlet.monkey_patch()

for i in range(25):
    pool.spawn(bw_updater)

pool.waitall()

print
