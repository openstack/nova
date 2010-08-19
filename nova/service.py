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
Generic Node baseclass for all workers that run on hosts
"""

import inspect
import logging
import os

from twisted.internet import defer
from twisted.internet import task
from twisted.application import service

from nova import exception
from nova import flags
from nova import models
from nova import rpc


FLAGS = flags.FLAGS

flags.DEFINE_integer('report_interval', 10,
                     'seconds between nodes reporting state to cloud',
                     lower_bound=1)

class Service(object, service.Service):
    """Base class for workers that run on hosts"""

    @classmethod
    def create(cls,
               report_interval=None, # defaults to flag
               bin_name=None, # defaults to basename of executable
               topic=None): # defaults to basename - "nova-" part
        """Instantiates class and passes back application object"""
        if not report_interval:
            # NOTE(vish): set here because if it is set to flag in the
            #             parameter list, it wrongly uses the default
            report_interval = FLAGS.report_interval
        # NOTE(vish): magic to automatically determine bin_name and topic
        if not bin_name:
            bin_name = os.path.basename(inspect.stack()[-1][1])
        if not topic:
            topic = bin_name.rpartition("nova-")[2]
        logging.warn("Starting %s node" % topic)
        node_instance = cls()

        conn = rpc.Connection.instance()
        consumer_all = rpc.AdapterConsumer(
                connection=conn,
                topic='%s' % topic,
                proxy=node_instance)

        consumer_node = rpc.AdapterConsumer(
                connection=conn,
                topic='%s.%s' % (topic, FLAGS.node_name),
                proxy=node_instance)

        pulse = task.LoopingCall(node_instance.report_state,
                                 FLAGS.node_name,
                                 bin_name)
        pulse.start(interval=report_interval, now=False)

        consumer_all.attach_to_twisted()
        consumer_node.attach_to_twisted()

        # This is the parent service that twistd will be looking for when it
        # parses this file, return it so that we can get it into globals below
        application = service.Application(bin_name)
        node_instance.setServiceParent(application)
        return application

    @defer.inlineCallbacks
    def report_state(self, node_name, binary):
        """Update the state of this daemon in the datastore"""
        # TODO(termie): make this pattern be more elegant. -todd
        try:
            try:
                #FIXME abstract this
                daemon = models.find_by_args(node_name, binary)
            except exception.NotFound():
                daemon = models.Daemon(node_name=node_name,
                                       binary=binary)
            self._update_daemon()
            self.commit()
            if getattr(self, "model_disconnected", False):
                self.model_disconnected = False
                logging.error("Recovered model server connection!")

        except Exception, ex: #FIXME this should only be connection error
            if not getattr(self, "model_disconnected", False):
                self.model_disconnected = True
                logging.exception("model server went away")
        yield

    def _update_daemon(daemon):
        """Set any extra daemon data here"""
        daemon.report_count = daemon.report_count + 1
