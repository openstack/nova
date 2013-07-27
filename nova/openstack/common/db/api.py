# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Rackspace Hosting
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

"""Multiple DB API backend support.

Supported configuration options:

The following two parameters are in the 'database' group:
`backend`: DB backend name or full module path to DB backend module.
`use_tpool`: Enable thread pooling of DB API calls.

A DB backend module should implement a method named 'get_backend' which
takes no arguments.  The method can return any object that implements DB
API methods.

*NOTE*: There are bugs in eventlet when using tpool combined with
threading locks. The python logging module happens to use such locks.  To
work around this issue, be sure to specify thread=False with
eventlet.monkey_patch().

A bug for eventlet has been filed here:

https://bitbucket.org/eventlet/eventlet/issue/137/
"""
import functools

from oslo.config import cfg

from nova.openstack.common import importutils
from nova.openstack.common import lockutils


db_opts = [
    cfg.StrOpt('backend',
               default='sqlalchemy',
               deprecated_name='db_backend',
               deprecated_group='DEFAULT',
               help='The backend to use for db'),
    cfg.BoolOpt('use_tpool',
                default=False,
                deprecated_name='dbapi_use_tpool',
                deprecated_group='DEFAULT',
                help='Enable the experimental use of thread pooling for '
                     'all DB API calls')
]

CONF = cfg.CONF
CONF.register_opts(db_opts, 'database')


class DBAPI(object):
    def __init__(self, backend_mapping=None):
        if backend_mapping is None:
            backend_mapping = {}
        self.__backend = None
        self.__backend_mapping = backend_mapping

    @lockutils.synchronized('dbapi_backend', 'nova-')
    def __get_backend(self):
        """Get the actual backend.  May be a module or an instance of
        a class.  Doesn't matter to us.  We do this synchronized as it's
        possible multiple greenthreads started very quickly trying to do
        DB calls and eventlet can switch threads before self.__backend gets
        assigned.
        """
        if self.__backend:
            # Another thread assigned it
            return self.__backend
        backend_name = CONF.database.backend
        self.__use_tpool = CONF.database.use_tpool
        if self.__use_tpool:
            from eventlet import tpool
            self.__tpool = tpool
        # Import the untranslated name if we don't have a
        # mapping.
        backend_path = self.__backend_mapping.get(backend_name,
                                                  backend_name)
        backend_mod = importutils.import_module(backend_path)
        self.__backend = backend_mod.get_backend()
        return self.__backend

    def __getattr__(self, key):
        backend = self.__backend or self.__get_backend()
        attr = getattr(backend, key)
        if not self.__use_tpool or not hasattr(attr, '__call__'):
            return attr

        def tpool_wrapper(*args, **kwargs):
            return self.__tpool.execute(attr, *args, **kwargs)

        functools.update_wrapper(tpool_wrapper, attr)
        return tpool_wrapper
