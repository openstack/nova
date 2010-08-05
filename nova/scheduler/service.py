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


class SchedulerService(service.Service):
    """
    Picks nodes for instances to run.
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
    def compute_identifiers(self):
        return [identifier for identifier in Redis.instance().smembers("daemons") if (identifier.split(':')[1] == "nova-compute")]

    def pick_node(self, instance_id, **_kwargs):
        identifiers = self.compute_identifiers
        return identifiers[int(random.random() * len(identifiers))].split(':')[0]

    @exception.wrap_exception
    def run_instance(self, instance_id, **_kwargs):
        node = self.pick_node(instance_id, **_kwargs)

        rpc.cast('%s.%s' % (FLAGS.compute_topic, node),
             {"method": "run_instance",
              "args": {"instance_id" : instance_id}})
        logging.debug("Casting to node %s for instance %s" %
                  (node, instance_id))


