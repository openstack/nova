# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

from oslo_config import cfg
from oslo_service import opts


# NOTE(gmaan): 'graceful_shutdown_timeout' is defined in oslo.service with
# default value of 60 which is too low for Nova services. Override its default
# here which will be applicable for all Nova services.
NOVA_DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT = 180
opts.set_service_opts_defaults(
    cfg.CONF,
    graceful_shutdown_timeout=NOVA_DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT)


base_options = [
    cfg.IntOpt(
        'password_length',
        default=12,
        min=0,
        help='Length of generated instance admin passwords.'),
    cfg.StrOpt(
        'instance_usage_audit_period',
        default='month',
        regex='^(hour|month|day|year)(@([0-9]+))?$',
        help='''
Time period to generate instance usages for. It is possible to define optional
offset to given period by appending @ character followed by a number defining
offset.

Possible values:

*  period, example: ``hour``, ``day``, ``month` or ``year``
*  period with offset, example: ``month@15`` will result in monthly audits
   starting on 15th day of month.
'''),
    cfg.BoolOpt(
        'use_rootwrap_daemon',
        default=False,
        help='''
Start and use a daemon that can run the commands that need to be run with
root privileges. This option is usually enabled on nodes that run nova compute
processes.
'''),
    cfg.StrOpt(
        'rootwrap_config',
        default="/etc/nova/rootwrap.conf",
        help='''
Path to the rootwrap configuration file.

Goal of the root wrapper is to allow a service-specific unprivileged user to
run a number of actions as the root user in the safest manner possible.
The configuration file used here must match the one defined in the sudoers
entry.
'''),
    cfg.StrOpt(
        'tempdir',
        help='Explicitly specify the temporary working directory.'),
    cfg.IntOpt(
        'default_green_pool_size',
        deprecated_for_removal=True,
        deprecated_since='32.0.0',
        deprecated_reason="""
This option is only used if the service is running in Eventlet mode. When
that mode is removed this config option will be removed too.
""",
        default=1000,
        min=100,
        help='''
The total number of coroutines that can be run via nova's default
greenthread pool concurrently, defaults to 1000, min value is 100. It is only
used if the service is running in Eventlet mode.
'''),
    cfg.StrOpt(
        'concurrency_backend',
        default='auto',
        choices=[
            ('auto', 'Use the per-binary deployment default. On Nova master '
                     'all services default to native threading except the '
                     'novnc/serial/spice console proxy services and CLI entry '
                     'points (nova-manage, nova-policy, nova-status). '
                     'This is the same as leaving the option unset.'),
            ('threading', 'Start the service with native threading. '
                          'Eventlet monkey patching is not applied.'),
            ('eventlet', 'Start the service with eventlet coroutine-based '
                         'concurrency. Eventlet monkey patching is applied. '
                         'This value is deprecated and will be removed no '
                         'earlier than the 2027.2 release.'),
        ],
        help="""
  Selects the concurrency backend used by Nova services.

  This option is read early in service startup, before oslo.config is fully
  initialised, so that eventlet monkey patching can be applied (or suppressed)
  before any other imports occur.

  When set to ``auto``, each Nova binary applies its own built-in deployment
  default. On Nova master all services default to native threading except the
  novnc/serial/spice console proxy services and CLI entry points (nova-manage,
  nova-policy, nova-status) which still default to eventlet. Setting an
  explicit value overrides the per-binary default for every service that reads
  this config file.

  The environment variable ``OS_NOVA_DISABLE_EVENTLET_PATCHING`` takes
  precedence over this option when both are set.

  See also the `concurrency admin guide`__.

  .. __: https://docs.openstack.org/nova/latest/admin/concurrency.html

  .. warning::

     Eventlet-based concurrency is deprecated and will be removed in a future
     release, not earlier than 2027.2. Operators should migrate to native
     threading.

  Related options:

  * ``[DEFAULT]/default_green_pool_size`` (only used in eventlet mode)
  * ``[DEFAULT]/default_thread_pool_size`` (only used in threading mode)
  * ``[DEFAULT]/cell_worker_thread_pool_size`` (only used in threading mode)
  """),
    cfg.IntOpt(
        'default_thread_pool_size',
        default=10,
        min=1,
        help='''
The total number of threads that can be run via nova's default
thread pool concurrently. It is only used if the service is running in
native threading mode.
'''),
    cfg.IntOpt(
        'cell_worker_thread_pool_size',
        default=5,
        min=1,
        help='''
The number of tasks that can run concurrently, one for each cell, for
operations requires cross cell data gathering a.k.a scatter-gather, like
listing instances across multiple cells. This is only used if the service is
running in native thread mode.
'''),
    cfg.IntOpt(
        'thread_pool_statistic_period',
        default=-1,
        min=-1,
        help='''
When new work is submitted to any of the thread pools nova logs the
statistics of the pool (work executed, threads available, work queued, etc).
This parameter defines how frequently such logging happens from a specific
pool in seconds. A value of 60 means that statistic will be logged
from a pool maximum once every 60 seconds. The value 0 means that logging
happens every time work is submitted to the pool. The value -1 means the
logging is disabled.
'''),
    cfg.IntOpt(
        'manager_shutdown_timeout',
        default=160,
        min=0,
        help="""
Specifies the total time in seconds for the manager to complete the
in-progress tasks. During a graceful shutdown, the manager will
attempt to finish the in-progress tasks within this period. If tasks
take a longer time, then we need to timeout that and let the service
complete the remaining graceful shutdown steps.

This timeout must be less than the overall graceful shutdown timeout
``[DEFAULT]/graceful_shutdown_timeout``.

Possible values:

* 0: The compute manager does not wait to finish in-progress tasks.
* A positive integer: Number of seconds the manager waits before the service
                      stops (The default value is 160).

Related options:

* ``[DEFAULT]/graceful_shutdown_timeout``
"""),
]


def register_opts(conf):
    conf.register_opts(base_options)


def list_opts():
    return {'DEFAULT': base_options}
