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
                    'nova.rpc.impl_kombu',
                    "The messaging module to use, defaults to kombu.")

_RPCIMPL = None


def get_impl():
    """Delay import of rpc_backend until FLAGS are loaded."""
    global _RPCIMPL
    if _RPCIMPL is None:
        _RPCIMPL = import_object(FLAGS.rpc_backend)
    return _RPCIMPL


def create_connection(new=True):
    return get_impl().create_connection(new=new)


def call(context, topic, msg):
    return get_impl().call(context, topic, msg)


def cast(context, topic, msg):
    return get_impl().cast(context, topic, msg)


def fanout_cast(context, topic, msg):
    return get_impl().fanout_cast(context, topic, msg)


def multicall(context, topic, msg):
    return get_impl().multicall(context, topic, msg)
