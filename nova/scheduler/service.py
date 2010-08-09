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
Scheduler Service
"""

import logging
from twisted.internet import defer

from nova import exception
from nova import flags
from nova import rpc
from nova import service
from nova.scheduler import scheduler

FLAGS = flags.FLAGS
flags.DEFINE_string('scheduler_type',
                    'random',
                    'the scheduler to use')

SCHEDULER_CLASSES = {'random': scheduler.RandomScheduler,
                     'bestfit': scheduler.BestFitScheduler}


class SchedulerService(service.Service):
    """
    Manages the running instances.
    """

    def __init__(self):
        super(SchedulerService, self).__init__()
        if (FLAGS.scheduler_type not in SCHEDULER_CLASSES):
            raise exception.Error("Scheduler '%s' does not exist" %
                                      FLAGS.scheduler_type)
        self._scheduler_class = SCHEDULER_CLASSES[FLAGS.scheduler_type]

    def noop(self):
        """ simple test of an AMQP message call """
        return defer.succeed('PONG')

    def pick_node(self, instance_id, **_kwargs):
        """
        Return a node to use based on the selected Scheduler
        """

        return self._scheduler_class().pick_node(instance_id, **_kwargs)

    @exception.wrap_exception
    def run_instance(self, instance_id, **_kwargs):
        """
        Picks a node for a running VM and casts the run_instance request
        """

        node = self.pick_node(instance_id, **_kwargs)

        rpc.cast('%s.%s' % (FLAGS.compute_topic, node),
             {"method": "run_instance",
              "args": {"instance_id": instance_id}})
        logging.debug("Casting to node %s for running instance %s",
                          node, instance_id)

