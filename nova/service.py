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
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_integer('report_interval', 10,
                     'seconds between nodes reporting state to cloud',
                     lower_bound=1)


class Service(object, service.Service):
    """Base class for workers that run on hosts."""

    def __init__(self, host, binary, topic, manager,
                 db_driver=None, *args, **kwargs):
        self.host = host
        self.binary = binary
        self.topic = topic
        manager_class = utils.import_class(manager)
        self.manager = manager_class(host, db_driver)
        self.model_disconnected = False
        super(Service, self).__init__(*args, **kwargs)

    def __getattr__(self, key):
        try:
            return super(Service, self).__getattr__(key)
        except AttributeError:
            return getattr(self.manager, key)

    @classmethod
    def create(cls,
               host=None,
               binary=None,
               topic=None,
               manager=None,
               report_interval=None):
        """Instantiates class and passes back application object.

        Args:
            host, defaults to FLAGS.host
            binary, defaults to basename of executable
            topic, defaults to bin_name - "nova-" part
            manager, defaults to FLAGS.<topic>_manager
            report_interval, defaults to FLAGS.report_interval
        """
        if not report_interval:
            report_interval = FLAGS.report_interval

        if not host:
            host = FLAGS.host
        if not binary:
            binary = os.path.basename(inspect.stack()[-1][1])
        if not topic:
            topic = binary.rpartition("nova-")[2]
        if not manager:
            manager = FLAGS.get('%s_manager' % topic, None)
        logging.warn("Starting %s node", topic)
        service_obj = cls(FLAGS.host, binary, topic, manager)
        conn = rpc.Connection.instance()
        consumer_all = rpc.AdapterConsumer(
                connection=conn,
                topic='%s' % topic,
                proxy=service_obj)
        consumer_node = rpc.AdapterConsumer(
                connection=conn,
                topic='%s.%s' % (topic, FLAGS.host),
                proxy=service_obj)

        pulse = task.LoopingCall(service_obj.report_state)
        pulse.start(interval=report_interval, now=False)

        consumer_all.attach_to_twisted()
        consumer_node.attach_to_twisted()

        # This is the parent service that twistd will be looking for when it
        # parses this file, return it so that we can get it into globals.
        application = service.Application(binary)
        service_obj.setServiceParent(application)
        return application

    @defer.inlineCallbacks
    def report_state(self, context=None):
        """Update the state of this daemon in the datastore."""
        try:
            try:
                daemon_ref = db.daemon_get_by_args(context,
                                                   self.host,
                                                   self.binary)
                daemon_id = daemon_ref['id']
            except exception.NotFound:
                daemon_id = db.daemon_create(context, {'host': self.host,
                                                       'binary': self.binary,
                                                       'topic': self.topic,
                                                       'report_count': 0})
                daemon_ref = db.daemon_get(context, daemon_id)
            db.daemon_update(context,
                             daemon_id,
                             {'report_count': daemon_ref['report_count'] + 1})

            # TODO(termie): make this pattern be more elegant.
            if getattr(self, "model_disconnected", False):
                self.model_disconnected = False
                logging.error("Recovered model server connection!")

        # TODO(vish): this should probably only catch connection errors
        except:  # pylint: disable-msg=W0702
            if not getattr(self, "model_disconnected", False):
                self.model_disconnected = True
                logging.exception("model server went away")
        yield
