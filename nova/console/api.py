# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Openstack, LLC.
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

"""Handles ConsoleProxy API requests."""

from nova import exception
from nova import flags
from nova import rpc
from nova.db import base


FLAGS = flags.FLAGS


class API(base.Base):
    """API for spinning up or down console proxy connections."""

    def __init__(self, **kwargs):
        super(API, self).__init__(**kwargs)

    def get_consoles(self, context, instance_id):
        return self.db.console_get_all_by_instance(context, instance_id)

    def get_console(self, context, instance_id, console_id):
        return self.db.console_get(context, console_id, instance_id)

    def delete_console(self, context, instance_id, console_id):
        console = self.db.console_get(context,
                                      console_id,
                                      instance_id)
        pool = console['pool']
        rpc.cast(context,
                 self.db.queue_get_for(context,
                                       FLAGS.console_topic,
                                       pool['host']),
                 {'method': 'remove_console',
                  'args': {'console_id': console['id']}})

    def create_console(self, context, instance_id):
        instance = self.db.instance_get(context, instance_id)
        #NOTE(mdragon): If we wanted to return this the console info
        #               here, as we would need to do a call.
        #               They can just do an index later to fetch
        #               console info. I am not sure which is better
        #               here.
        rpc.cast(context,
                 self._get_console_topic(context, instance['host']),
                 {'method': 'add_console',
                  'args': {'instance_id': instance_id}})

    def _get_console_topic(self, context, instance_host):
        topic = self.db.queue_get_for(context,
                                      FLAGS.compute_topic,
                                      instance_host)
        return rpc.call(context, topic, {'method': 'get_console_topic',
                                         'args': {'fake': 1}})
