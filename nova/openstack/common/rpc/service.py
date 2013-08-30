# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2011 Red Hat, Inc.
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

from nova.openstack.common.gettextutils import _  # noqa
from nova.openstack.common import log as logging
from nova.openstack.common import rpc
from nova.openstack.common.rpc import dispatcher as rpc_dispatcher
from nova.openstack.common import service


LOG = logging.getLogger(__name__)


class Service(service.Service):
    """Service object for binaries running on hosts.

    A service enables rpc by listening to queues based on topic and host.
    """
    def __init__(self, host, topic, manager=None, serializer=None):
        super(Service, self).__init__()
        self.host = host
        self.topic = topic
        self.serializer = serializer
        if manager is None:
            self.manager = self
        else:
            self.manager = manager

    def start(self):
        super(Service, self).start()

        self.conn = rpc.create_connection(new=True)
        LOG.debug(_("Creating Consumer connection for Service %s") %
                  self.topic)

        dispatcher = rpc_dispatcher.RpcDispatcher([self.manager],
                                                  self.serializer)

        # Share this same connection for these Consumers
        self.conn.create_consumer(self.topic, dispatcher, fanout=False)

        node_topic = '%s.%s' % (self.topic, self.host)
        self.conn.create_consumer(node_topic, dispatcher, fanout=False)

        self.conn.create_consumer(self.topic, dispatcher, fanout=True)

        # Hook to allow the manager to do other initializations after
        # the rpc connection is created.
        if callable(getattr(self.manager, 'initialize_service_hook', None)):
            self.manager.initialize_service_hook(self)

        # Consume from all consumers in a thread
        self.conn.consume_in_thread()

    def stop(self):
        # Try to shut the connection down, but if we get any sort of
        # errors, go ahead and ignore them.. as we're shutting down anyway
        try:
            self.conn.close()
        except Exception:
            pass
        super(Service, self).stop()
