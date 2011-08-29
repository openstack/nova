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

from eventlet import greenthread

from nova import context
from nova import db
from nova import flags
from nova import log as logging
from nova import rpc
from nova import test
from nova import utils
from nova.api.ec2 import admin
from nova.image import fake


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.adminapi')


class AdminApiTestCase(test.TestCase):
    def setUp(self):
        super(AdminApiTestCase, self).setUp()
        self.flags(connection_type='fake')

        # set up our cloud
        self.api = admin.AdminController()

        # set up services
        self.compute = self.start_service('compute')
        self.scheduter = self.start_service('scheduler')
        self.network = self.start_service('network')
        self.volume = self.start_service('volume')
        self.image_service = utils.import_object(FLAGS.image_service)

        self.user_id = 'admin'
        self.project_id = 'admin'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id,
                                              True)

        def fake_show(meh, context, id):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                    'type': 'machine', 'image_state': 'available'}}

        self.stubs.Set(fake._FakeImageService, 'show', fake_show)
        self.stubs.Set(fake._FakeImageService, 'show_by_name', fake_show)

        # NOTE(vish): set up a manual wait so rpc.cast has a chance to finish
        rpc_cast = rpc.cast

        def finish_cast(*args, **kwargs):
            rpc_cast(*args, **kwargs)
            greenthread.sleep(0.2)

        self.stubs.Set(rpc, 'cast', finish_cast)

    def test_block_external_ips(self):
        """Make sure provider firewall rules are created."""
        result = self.api.block_external_addresses(self.context, '1.1.1.1/32')
        self.api.remove_external_address_block(self.context, '1.1.1.1/32')
        self.assertEqual('OK', result['status'])
        self.assertEqual('Added 3 rules', result['message'])

    def test_list_blocked_ips(self):
        """Make sure we can see the external blocks that exist."""
        self.api.block_external_addresses(self.context, '1.1.1.2/32')
        result = self.api.describe_external_address_blocks(self.context)
        num = len(db.provider_fw_rule_get_all(self.context))
        self.api.remove_external_address_block(self.context, '1.1.1.2/32')
        # we only list IP, not tcp/udp/icmp rules
        self.assertEqual(num / 3, len(result['externalIpBlockInfo']))

    def test_remove_ip_block(self):
        """Remove ip blocks."""
        result = self.api.block_external_addresses(self.context, '1.1.1.3/32')
        self.assertEqual('OK', result['status'])
        num0 = len(db.provider_fw_rule_get_all(self.context))
        result = self.api.remove_external_address_block(self.context,
                                                        '1.1.1.3/32')
        self.assertEqual('OK', result['status'])
        self.assertEqual('Deleted 3 rules', result['message'])
        num1 = len(db.provider_fw_rule_get_all(self.context))
        self.assert_(num1 < num0)
