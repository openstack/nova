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

from oslo_cache import core as cache
from oslo_db import options
from oslo_log import log

from nova.common import config
import nova.conf
from nova.db.sqlalchemy import api as sqlalchemy_api
from nova import paths
from nova import rpc
from nova import version


CONF = nova.conf.CONF

_DEFAULT_SQL_CONNECTION = 'sqlite:///' + paths.state_path_def('nova.sqlite')

_EXTRA_DEFAULT_LOG_LEVELS = ['glanceclient=WARN']


def parse_args(argv, default_config_files=None, configure_db=True,
               init_rpc=True):
    log.register_options(CONF)
    # We use the oslo.log default log levels which includes suds=INFO
    # and add only the extra levels that Nova needs
    log.set_defaults(default_log_levels=log.get_default_log_levels() +
                     _EXTRA_DEFAULT_LOG_LEVELS)
    options.set_defaults(CONF, connection=_DEFAULT_SQL_CONNECTION,
                         sqlite_db='nova.sqlite')
    rpc.set_defaults(control_exchange='nova')
    cache.configure(CONF)
    config.set_middleware_defaults()

    CONF(argv[1:],
         project='nova',
         version=version.version_string(),
         default_config_files=default_config_files)

    if init_rpc:
        rpc.init(CONF)

    if configure_db:
        sqlalchemy_api.configure(CONF)
