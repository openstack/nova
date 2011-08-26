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


from nova.utils import import_object
from nova.rpc.common import RemoteError, LOG
from nova import flags

FLAGS = flags.FLAGS
flags.DEFINE_string('rpc_backend',
                    'carrot',
                    "The messaging module to use, defaults to carrot.")

impl_table = {'kombu': 'nova.rpc.impl_kombu',
                'amqp': 'nova.rpc.impl_kombu',
                'carrot': 'nova.rpc.impl_carrot'}


# rpc_backend can be a short name like 'kombu', or it can be the full
# module name
RPCIMPL = import_object(impl_table.get(FLAGS.rpc_backend,
        FLAGS.rpc_backend))


def create_connection(new=True):
    return RPCIMPL.Connection.instance(new=True)


def create_consumer(conn, topic, proxy, fanout=False):
    return RPCIMPL.create_consumer(conn, topic, proxy, fanout)


def create_consumer_set(conn, consumers):
    # FIXME(comstud): replace however necessary
    return RPCIMPL.ConsumerSet(connection=conn, consumer_list=consumers)


def call(context, topic, msg):
    return RPCIMPL.call(context, topic, msg)


def cast(context, topic, msg):
    return RPCIMPL.cast(context, topic, msg)


def fanout_cast(context, topic, msg):
    return RPCIMPL.fanout_cast(context, topic, msg)


def multicall(context, topic, msg):
    return RPCIMPL.multicall(context, topic, msg)
