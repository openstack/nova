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

from nova import datastore
from nova import flags
from nova import rpc
from nova.compute import model


FLAGS = flags.FLAGS

flags.DEFINE_integer('report_interval', 10,
                     'seconds between nodes reporting state to cloud',
                     lower_bound=1)

class Node(object, service.Service):
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
    def report_state(self, nodename, daemon):
        # TODO(termie): make this pattern be more elegant. -todd
        try:
            record = model.Daemon(nodename, daemon)
            record.heartbeat()
            if getattr(self, "model_disconnected", False):
                self.model_disconnected = False
                logging.error("Recovered model server connection!")

        except datastore.ConnectionError, ex:
            if not getattr(self, "model_disconnected", False):
                self.model_disconnected = True
                logging.exception("model server went away")
        yield
