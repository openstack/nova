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

from nova import db
from nova import exception
from nova import flags
from nova import rpc


FLAGS = flags.FLAGS
flags.DEFINE_integer('report_interval', 10,
                     'seconds between nodes reporting state to cloud',
                     lower_bound=1)


class Service(object, service.Service):
    """Base class for workers that run on hosts."""

    @classmethod
    def create(cls, report_interval=None, bin_name=None, topic=None):
        """Instantiates class and passes back application object.

        Args:
            report_interval, defaults to flag
            bin_name, defaults to basename of executable
            topic, defaults to basename - "nova-" part

        """
        if not report_interval:
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
        # parses this file, return it so that we can get it into globals.
        application = service.Application(bin_name)
        node_instance.setServiceParent(application)
        return application

    @defer.inlineCallbacks
    def report_state(self, node_name, binary, context=None):
        """Update the state of this daemon in the datastore."""
        try:
            try:
                daemon_ref = db.daemon_get_by_args(context, node_name, binary)
                daemon_id = daemon_ref['id']
            except exception.NotFound:
                daemon_id = db.daemon_create(context, {'node_name': node_name,
                                                        'binary': binary,
                                                        'report_count': 0})
                daemon_ref = db.daemon_get(context, daemon_id)
            db.daemon_update(context,
                             daemon_id,
                             {'report_count': daemon_ref['report_count'] + 1})

            # TODO(termie): make this pattern be more elegant.
            if getattr(self, "model_disconnected", False):
                self.model_disconnected = False
                logging.error("Recovered model server connection!")

        except Exception, ex: #FIXME this should only be connection error
            if not getattr(self, "model_disconnected", False):
                self.model_disconnected = True
                logging.exception("model server went away")
        yield
