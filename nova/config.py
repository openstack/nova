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
from oslo_policy import opts as policy_opts
from oslo_utils import importutils

import nova.conf
from nova.db.api import api as api_db_api
from nova.db.main import api as main_db_api
from nova import middleware
from nova import policy
from nova import rpc
from nova import version

profiler = importutils.try_import('osprofiler.opts')


CONF = nova.conf.CONF


def set_lib_defaults():
    """Update default value for configuration options from other namespace.

    Example, oslo lib config options. This is needed for
    config generator tool to pick these default value changes.
    https://docs.openstack.org/oslo.config/latest/cli/
    generator.html#modifying-defaults-from-other-namespaces
    """

    # Update default value of oslo.middleware cors config option.
    middleware.set_defaults()

    # Update default value of RPC transport control_exchange config option.
    rpc.set_defaults(control_exchange='nova')

    # Update default value of oslo_log default_log_levels and
    # logging_context_format_string config option.
    set_log_defaults()

    # Update default value of oslo.policy policy_file config option.
    policy_opts.set_defaults(CONF, policy.DEFAULT_POLICY_FILE)


def rabbit_heartbeat_filter(log_record):
    message = "Unexpected error during heartbeat thread processing"
    return message not in log_record.msg


def set_log_defaults():
    # We use the oslo.log default log levels which includes suds=INFO
    # and add only the extra levels that Nova needs
    if CONF.glance.debug:
        extra_default_log_levels = ['glanceclient=DEBUG']
    else:
        extra_default_log_levels = ['glanceclient=WARN']
    # NOTE(danms): DEBUG logging in privsep will result in some large
    # and potentially sensitive things being logged.
    extra_default_log_levels.append('oslo.privsep.daemon=INFO')

    log.set_defaults(default_log_levels=log.get_default_log_levels() +
                     extra_default_log_levels)


def parse_args(argv, default_config_files=None, configure_db=True,
               init_rpc=True):
    log.register_options(CONF)

    # NOTE(sean-k-mooney): this filter addresses bug #1825584
    # https://bugs.launchpad.net/nova/+bug/1825584
    # eventlet monkey-patching breaks AMQP heartbeat on uWSGI
    rabbit_logger = logging.getLogger('oslo.messaging._drivers.impl_rabbit')
    rabbit_logger.addFilter(rabbit_heartbeat_filter)

    set_lib_defaults()
    if profiler:
        profiler.set_defaults(CONF)

    CONF(argv[1:],
         project='nova',
         version=version.version_string(),
         default_config_files=default_config_files)

    if init_rpc:
        rpc.init(CONF)

    if configure_db:
        main_db_api.configure(CONF)
        api_db_api.configure(CONF)
