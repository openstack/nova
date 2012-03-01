# Copyright (c) 2011 Openstack, LLC.
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

"""
Handles all requests relating to schedulers.
"""

from nova import flags
from nova import log as logging
from nova import rpc

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


def _call_scheduler(method, context, params=None):
    """Generic handler for RPC calls to the scheduler.

    :param params: Optional dictionary of arguments to be passed to the
                   scheduler worker

    :retval: Result returned by scheduler worker
    """
    if not params:
        params = {}
    queue = FLAGS.scheduler_topic
    kwargs = {'method': method, 'args': params}
    return rpc.call(context, queue, kwargs)


def get_host_list(context):
    """Return a list of hosts associated with this zone."""
    return _call_scheduler('get_host_list', context)


def get_service_capabilities(context):
    """Return aggregated capabilities for all services."""
    return _call_scheduler('get_service_capabilities', context)


def update_service_capabilities(context, service_name, host, capabilities):
    """Send an update to all the scheduler services informing them
       of the capabilities of this service."""
    kwargs = dict(method='update_service_capabilities',
                  args=dict(service_name=service_name, host=host,
                            capabilities=capabilities))
    return rpc.fanout_cast(context, 'scheduler', kwargs)


def live_migration(context, block_migration, disk_over_commit,
                   instance_id, dest, topic):
    """Migrate a server to a new host"""
    params = {"instance_id": instance_id,
              "dest": dest,
              "topic": topic,
              "block_migration": block_migration,
              "disk_over_commit": disk_over_commit}
    # NOTE(comstud): Call vs cast so we can get exceptions back, otherwise
    # this call in the scheduler driver doesn't return anything.
    _call_scheduler("live_migration", context=context, params=params)
