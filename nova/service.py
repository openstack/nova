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
A service is a very thin wrapper around a Manager object.  It exposes the
manager's public methods to other components of the system via rpc.  It will
report state periodically to the database and is responsible for initiating any periodic tasts that need to be executed on a given host.

This module contains Service, a generic baseclass for all workers.
"""

import inspect
import logging
import os

from twisted.internet import defer
from twisted.internet import task
from twisted.application import service

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import rpc
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_integer('report_interval', 10,
                     'seconds between nodes reporting state to datastore',
                     lower_bound=1)

flags.DEFINE_integer('periodic_interval', 60,
                     'seconds between running periodic tasks',
                     lower_bound=1)


class Service(object, service.Service):
    """Base class for workers that run on hosts."""

    def __init__(self, host, binary, topic, manager, report_interval=None,
                 periodic_interval=None, *args, **kwargs):
        self.host = host
        self.binary = binary
        self.topic = topic
        self.manager_class_name = manager
        self.report_interval = report_interval
        self.periodic_interval = periodic_interval
        super(Service, self).__init__(*args, **kwargs)
        self.saved_args, self.saved_kwargs = args, kwargs

    def startService(self):  # pylint: disable-msg C0103
        manager_class = utils.import_class(self.manager_class_name)
        self.manager = manager_class(host=self.host, *self.saved_args,
                                                     **self.saved_kwargs)
        self.manager.init_host()
        self.model_disconnected = False
        ctxt = context.get_admin_context()
        try:
            service_ref = db.service_get_by_args(ctxt,
                                                 self.host,
                                                 self.binary)
            self.service_id = service_ref['id']
        except exception.NotFound:
            self._create_service_ref(ctxt)

        conn = rpc.Connection.instance()
        if self.report_interval:
            consumer_all = rpc.AdapterConsumer(
                    connection=conn,
                    topic=self.topic,
                    proxy=self)
            consumer_node = rpc.AdapterConsumer(
                    connection=conn,
                    topic='%s.%s' % (self.topic, self.host),
                    proxy=self)

            consumer_all.attach_to_twisted()
            consumer_node.attach_to_twisted()

            pulse = task.LoopingCall(self.report_state)
            pulse.start(interval=self.report_interval, now=False)

        if self.periodic_interval:
            pulse = task.LoopingCall(self.periodic_tasks)
            pulse.start(interval=self.periodic_interval, now=False)

    def _create_service_ref(self, context):
        service_ref = db.service_create(context,
                                        {'host': self.host,
                                         'binary': self.binary,
                                         'topic': self.topic,
                                         'report_count': 0})
        self.service_id = service_ref['id']

    def __getattr__(self, key):
        manager = self.__dict__.get('manager', None)
        return getattr(manager, key)

    @classmethod
    def create(cls,
               host=None,
               binary=None,
               topic=None,
               manager=None,
               report_interval=None,
               periodic_interval=None):
        """Instantiates class and passes back application object.

        Args:
            host, defaults to FLAGS.host
            binary, defaults to basename of executable
            topic, defaults to bin_name - "nova-" part
            manager, defaults to FLAGS.<topic>_manager
            report_interval, defaults to FLAGS.report_interval
            periodic_interval, defaults to FLAGS.periodic_interval
        """
        if not host:
            host = FLAGS.host
        if not binary:
            binary = os.path.basename(inspect.stack()[-1][1])
        if not topic:
            topic = binary.rpartition("nova-")[2]
        if not manager:
            manager = FLAGS.get('%s_manager' % topic, None)
        if not report_interval:
            report_interval = FLAGS.report_interval
        if not periodic_interval:
            periodic_interval = FLAGS.periodic_interval
        logging.warn("Starting %s node", topic)
        service_obj = cls(host, binary, topic, manager,
                          report_interval, periodic_interval)

        # This is the parent service that twistd will be looking for when it
        # parses this file, return it so that we can get it into globals.
        application = service.Application(binary)
        service_obj.setServiceParent(application)
        return application

    def kill(self):
        """Destroy the service object in the datastore"""
        try:
            db.service_destroy(context.get_admin_context(), self.service_id)
        except exception.NotFound:
            logging.warn("Service killed that has no database entry")

    @defer.inlineCallbacks
    def periodic_tasks(self):
        """Tasks to be run at a periodic interval"""
        yield self.manager.periodic_tasks(context.get_admin_context())

    @defer.inlineCallbacks
    def report_state(self):
        """Update the state of this service in the datastore."""
        ctxt = context.get_admin_context()
        try:
            try:
                service_ref = db.service_get(ctxt, self.service_id)
            except exception.NotFound:
                logging.debug("The service database object disappeared, "
                              "Recreating it.")
                self._create_service_ref(ctxt)
                service_ref = db.service_get(ctxt, self.service_id)

            db.service_update(ctxt,
                             self.service_id,
                             {'report_count': service_ref['report_count'] + 1})

            # TODO(termie): make this pattern be more elegant.
            if getattr(self, "model_disconnected", False):
                self.model_disconnected = False
                logging.error("Recovered model server connection!")

        # TODO(vish): this should probably only catch connection errors
        except Exception:  # pylint: disable-msg=W0702
            if not getattr(self, "model_disconnected", False):
                self.model_disconnected = True
                logging.exception("model server went away")
        yield
