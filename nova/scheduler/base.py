# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Openstack, LLC.
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
Scheduler base class that all Schedulers should inherit from
"""

import time

from nova import flags
from nova.datastore import Redis

FLAGS = flags.FLAGS
flags.DEFINE_integer('node_down_time',
                     60,
                     'seconds without heartbeat that determines a '
                         'compute node to be down')


class Scheduler(object):
    """
    The base class that all Scheduler clases should inherit from
    """

    @property
    def compute_nodes(self):
        return [identifier.split(':')[0]
                   for identifier in Redis.instance().smembers("daemons")
                       if (identifier.split(':')[1] == "nova-compute")]

    def compute_node_is_up(self, node):
        time_str = Redis.instance().hget('%s:%s:%s' %
                                            ('daemon', node, 'nova-compute'),
                                         'updated_at')
        if not time_str:
            return False

        # Would be a lot easier if we stored heartbeat time in epoch :)

        # The 'str()' here is to get rid of a pylint error
        time_str = str(time_str).replace('Z', 'UTC')
        time_split = time.strptime(time_str, '%Y-%m-%dT%H:%M:%S%Z')
        epoch_time = int(time.mktime(time_split)) - time.timezone
        return (time.time() - epoch_time) < FLAGS.node_down_time

    def compute_nodes_up(self):
        return [node for node in self.compute_nodes
                   if self.compute_node_is_up(node)]

    def pick_node(self, instance_id, **_kwargs):
        """You DEFINITELY want to define this in your subclass"""
        raise NotImplementedError("Your subclass should define pick_node")
