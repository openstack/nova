# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 OpenStack Foundation
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

"""Admin/debug script to wipe rabbitMQ (AMQP) queues nova uses.
   This can be used if you need to change durable options on queues,
   or to wipe all messages in the queue system if things are in a
   serious bad way.

"""

import sys

from oslo.config import cfg

from nova import config
from nova.openstack.common import log as logging
from nova.openstack.common import rpc


opts = [
    cfg.MultiStrOpt('queues',
                    default=[],
                    positional=True,
                    help='Queues to delete'),
    cfg.BoolOpt('delete_exchange',
                default=False,
                help='delete nova exchange too.'),
]

CONF = cfg.CONF
CONF.register_cli_opts(opts)


def delete_exchange(exch):
    conn = rpc.create_connection()
    x = conn.get_channel()
    x.exchange_delete(exch)


def delete_queues(queues):
    conn = rpc.create_connection()
    x = conn.get_channel()
    for q in queues:
        x.queue_delete(q)


def main():
    config.parse_args(sys.argv)
    logging.setup("nova")
    delete_queues(CONF.queues)
    if CONF.delete_exchange:
        delete_exchange(CONF.control_exchange)
