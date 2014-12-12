# Copyright 2013, Red Hat, Inc.
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
Client side of the scheduler manager RPC API.
"""

from oslo.config import cfg
from oslo import messaging

from nova.objects import base as objects_base
from nova import rpc

rpcapi_opts = [
    cfg.StrOpt('scheduler_topic',
               default='scheduler',
               help='The topic scheduler nodes listen on'),
]

CONF = cfg.CONF
CONF.register_opts(rpcapi_opts)

rpcapi_cap_opt = cfg.StrOpt('scheduler',
        help='Set a version cap for messages sent to scheduler services')
CONF.register_opt(rpcapi_cap_opt, 'upgrade_levels')


class SchedulerAPI(object):
    '''Client side of the scheduler rpc API.

    API version history:

        * 1.0 - Initial version.
        * 1.1 - Changes to prep_resize():
            * remove instance_uuid, add instance
            * remove instance_type_id, add instance_type
            * remove topic, it was unused
        * 1.2 - Remove topic from run_instance, it was unused
        * 1.3 - Remove instance_id, add instance to live_migration
        * 1.4 - Remove update_db from prep_resize
        * 1.5 - Add reservations argument to prep_resize()
        * 1.6 - Remove reservations argument to run_instance()
        * 1.7 - Add create_volume() method, remove topic from live_migration()

        * 2.0 - Remove 1.x backwards compat
        * 2.1 - Add image_id to create_volume()
        * 2.2 - Remove reservations argument to create_volume()
        * 2.3 - Remove create_volume()
        * 2.4 - Change update_service_capabilities()
            * accepts a list of capabilities
        * 2.5 - Add get_backdoor_port()
        * 2.6 - Add select_hosts()

        ... Grizzly supports message version 2.6.  So, any changes to existing
        methods in 2.x after that point should be done such that they can
        handle the version_cap being set to 2.6.

        * 2.7 - Add select_destinations()
        * 2.8 - Deprecate prep_resize() -- JUST KIDDING.  It is still used
                by the compute manager for retries.
        * 2.9 - Added the legacy_bdm_in_spec parameter to run_instance()

        ... Havana supports message version 2.9.  So, any changes to existing
        methods in 2.x after that point should be done such that they can
        handle the version_cap being set to 2.9.

        * Deprecated live_migration() call, moved to conductor
        * Deprecated select_hosts()

        3.0 - Removed backwards compat

        ... Icehouse and Juno support message version 3.0.  So, any changes to
        existing methods in 3.x after that point should be done such that they
        can handle the version_cap being set to 3.0.

        * 3.1 - Made select_destinations() send flavor object

        * 4.0 - Removed backwards compat for Icehouse


    '''

    VERSION_ALIASES = {
        'grizzly': '2.6',
        'havana': '2.9',
        'icehouse': '3.0',
        'juno': '3.0',
        'kilo': '4.0',
    }

    def __init__(self):
        super(SchedulerAPI, self).__init__()
        target = messaging.Target(topic=CONF.scheduler_topic, version='4.0')
        version_cap = self.VERSION_ALIASES.get(CONF.upgrade_levels.scheduler,
                                               CONF.upgrade_levels.scheduler)
        serializer = objects_base.NovaObjectSerializer()
        self.client = rpc.get_client(target, version_cap=version_cap,
                                     serializer=serializer)

    def select_destinations(self, ctxt, request_spec, filter_properties):
        cctxt = self.client.prepare(version='4.0')
        return cctxt.call(ctxt, 'select_destinations',
            request_spec=request_spec, filter_properties=filter_properties)
