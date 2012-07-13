# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012, Red Hat, Inc.
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
Client side of the console RPC API.
"""

from nova import flags
import nova.openstack.common.rpc.proxy


FLAGS = flags.FLAGS


class ConsoleAPI(nova.openstack.common.rpc.proxy.RpcProxy):
    '''Client side of the console rpc API.

    API version history:

        1.0 - Initial version.
    '''

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, topic=None):
        topic = topic if topic else FLAGS.console_topic
        super(ConsoleAPI, self).__init__(
                topic=topic,
                default_version=self.BASE_RPC_API_VERSION)

    def add_console(self, ctxt, instance_id):
        self.cast(ctxt, self.make_msg('add_console', instance_id=instance_id))

    def remove_console(self, ctxt, console_id):
        self.cast(ctxt, self.make_msg('remove_console', console_id=console_id))
