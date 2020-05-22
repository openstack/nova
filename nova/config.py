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

import logging

from oslo_log import log
from oslo_utils import importutils

import nova.conf
from nova.db.sqlalchemy import api as sqlalchemy_api
from nova import middleware
from nova import rpc
from nova import version

profiler = importutils.try_import('osprofiler.opts')


CONF = nova.conf.CONF


def rabbit_heartbeat_filter(log_record):
    message = "Unexpected error during heartbeat thread processing"
    return message not in log_record.msg


def parse_args(argv, default_config_files=None, configure_db=True,
               init_rpc=True):
    log.register_options(CONF)
    # We use the oslo.log default log levels which includes suds=INFO
    # and add only the extra levels that Nova needs
    if CONF.glance.debug:
        extra_default_log_levels = ['glanceclient=DEBUG']
    else:
        extra_default_log_levels = ['glanceclient=WARN']

    # NOTE(sean-k-mooney): this filter addresses bug #1825584
    # https://bugs.launchpad.net/nova/+bug/1825584
    # eventlet monkey-patching breaks AMQP heartbeat on uWSGI
    rabbit_logger = logging.getLogger('oslo.messaging._drivers.impl_rabbit')
    rabbit_logger.addFilter(rabbit_heartbeat_filter)

    # NOTE(danms): DEBUG logging in privsep will result in some large
    # and potentially sensitive things being logged.
    extra_default_log_levels.append('oslo.privsep.daemon=INFO')

    log.set_defaults(default_log_levels=log.get_default_log_levels() +
                     extra_default_log_levels)
    rpc.set_defaults(control_exchange='nova')
    if profiler:
        profiler.set_defaults(CONF)
    middleware.set_defaults()

    CONF(argv[1:],
         project='nova',
         version=version.version_string(),
         default_config_files=default_config_files)

    if init_rpc:
        rpc.init(CONF)

    if configure_db:
        sqlalchemy_api.configure(CONF)
