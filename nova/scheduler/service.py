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

"""
Scheduler Service
"""

import logging
import random
import sys
import time
from twisted.internet import defer
from twisted.internet import task

from nova import exception
from nova import flags
from nova import process
from nova import rpc
from nova import service
from nova import utils
from nova.compute import model
from nova.datastore import Redis

FLAGS = flags.FLAGS
flags.DEFINE_integer('node_down_time', 60,
                    'seconds without heartbeat that determines a compute node to be down')

class SchedulerService(service.Service):
    """
    Manages the running instances.
    """
    def __init__(self):
        super(SchedulerService, self).__init__()
        self.instdir = model.InstanceDirectory()

    def noop(self):
        """ simple test of an AMQP message call """
        return defer.succeed('PONG')

    @defer.inlineCallbacks
    def report_state(self, nodename, daemon):
        # TODO(termie): make this pattern be more elegant. -todd
        try:
            record = model.Daemon(nodename, daemon)
            record.heartbeat()
            if getattr(self, "model_disconnected", False):
                self.model_disconnected = False
                logging.error("Recovered model server connection!")

        except model.ConnectionError, ex:
            if not getattr(self, "model_disconnected", False):
                self.model_disconnected = True
                logging.exception("model server went away")
        yield

    @property
    def compute_nodes(self):
        return [identifier.split(':')[0] for identifier in Redis.instance().smembers("daemons") if (identifier.split(':')[1] == "nova-compute")]

    def compute_node_is_up(self, node):
        time_str = Redis.instance().hget('%s:%s:%s' % ('daemon', node, 'nova-compute'), 'updated_at')
        return(time_str and
           (time.time() - (int(time.mktime(time.strptime(time_str.replace('Z', 'UTC'), '%Y-%m-%dT%H:%M:%S%Z'))) - time.timezone) < FLAGS.node_down_time))

    def compute_nodes_up(self):
        return [node for node in self.compute_nodes if self.compute_node_is_up(node)]

    def pick_node(self, instance_id, **_kwargs):
        """You DEFINITELY want to define this in your subclass"""
        raise NotImplementedError("Your subclass should define pick_node")

    @exception.wrap_exception
    def run_instance(self, instance_id, **_kwargs):
        node = self.pick_node(instance_id, **_kwargs)

        rpc.cast('%s.%s' % (FLAGS.compute_topic, node),
             {"method": "run_instance",
              "args": {"instance_id" : instance_id}})
        logging.debug("Casting to node %s for instance %s" %
                  (node, instance_id))

class RandomService(SchedulerService):
    """
    Implements SchedulerService as a random node selector
    """

    def __init__(self):
        super(RandomService, self).__init__()

    def pick_node(self, instance_id, **_kwargs):
        nodes = self.compute_nodes_up()
        return nodes[int(random.random() * len(nodes))]


