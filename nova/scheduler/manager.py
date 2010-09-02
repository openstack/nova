# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Openstack, LLC.
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

from nova import db
from nova import flags
from nova import manager
from nova import rpc
from nova import utils

FLAGS = flags.FLAGS
flags.DEFINE_string('scheduler_driver',
                    'nova.scheduler.chance.ChanceScheduler',
                    'Driver to use for the scheduler')


class SchedulerManager(manager.Manager):
    """
    Chooses a host to run instances on.
    """
    def __init__(self, scheduler_driver=None, *args, **kwargs):
        if not scheduler_driver:
            scheduler_driver = FLAGS.scheduler_driver
        self.driver = utils.import_object(scheduler_driver)
        super(SchedulerManager, self).__init__(*args, **kwargs)

    def run_instance(self, context, instance_id, **_kwargs):
        """
        Picks a node for a running VM and casts the run_instance request
        """

        host = self.driver.pick_host(context, instance_id, **_kwargs)

        rpc.cast(db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "run_instance",
                  "args": {"context": context,
                           "instance_id": instance_id}})
        logging.debug("Casting to compute %s for running instance %s",
                      host, instance_id)
