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
LOG = logging.getLogger('nova.scheduler.api')


class API(object):
    """API for interacting with the scheduler."""

    def _call_scheduler(self, method, context, params=None):
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

    def get_zone_list(self, context):
        items = self._call_scheduler('get_zone_list', context)
        for item in items:
            item['api_url'] = item['api_url'].replace('\\/', '/')
        return items
