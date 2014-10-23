# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2012 Red Hat, Inc.
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

from oslo.config import cfg
from oslo.db import options

from nova import debugger
from nova.openstack.common import log
from nova import paths
from nova import rpc
from nova import version


CONF = cfg.CONF

_DEFAULT_SQL_CONNECTION = 'sqlite:///' + paths.state_path_def('nova.sqlite')

_DEFAULT_LOG_LEVELS = ['amqp=WARN', 'amqplib=WARN', 'boto=WARN',
                       'qpid=WARN', 'sqlalchemy=WARN', 'suds=INFO',
                       'oslo.messaging=INFO', 'iso8601=WARN',
                       'requests.packages.urllib3.connectionpool=WARN',
                       'urllib3.connectionpool=WARN', 'websocket=WARN',
                       'keystonemiddleware=WARN', 'routes.middleware=WARN',
                       'stevedore=WARN', 'glanceclient=WARN']

_DEFAULT_LOGGING_CONTEXT_FORMAT = ('%(asctime)s.%(msecs)03d %(process)d '
                                   '%(levelname)s %(name)s [%(request_id)s '
                                   '%(user_identity)s] %(instance)s'
                                   '%(message)s')


def parse_args(argv, default_config_files=None):
    log.set_defaults(_DEFAULT_LOGGING_CONTEXT_FORMAT, _DEFAULT_LOG_LEVELS)
    options.set_defaults(CONF, connection=_DEFAULT_SQL_CONNECTION,
                         sqlite_db='nova.sqlite')
    rpc.set_defaults(control_exchange='nova')
    debugger.register_cli_opts()
    CONF(argv[1:],
         project='nova',
         version=version.version_string(),
         default_config_files=default_config_files)
    rpc.init(CONF)
