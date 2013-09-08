# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NTT DOCOMO, INC.
# Copyright (c) 2011 University of Southern California / ISI
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

from nova.virt.baremetal import base
from nova.virt import firewall


class FakeDriver(base.NodeDriver):

    def cache_images(self, context, node, instance, **kwargs):
        pass

    def destroy_images(self, context, node, instance):
        pass

    def activate_bootloader(self, context, node, instance, **kwargs):
        pass

    def deactivate_bootloader(self, context, node, instance):
        pass

    def activate_node(self, context, node, instance):
        """For operations after power on."""
        pass

    def deactivate_node(self, context, node, instance):
        """For operations before power off."""
        pass

    def get_console_output(self, node, instance):
        return 'fake\nconsole\noutput for instance %s' % instance['id']


class FakePowerManager(base.PowerManager):

    def __init__(self, **kwargs):
        super(FakePowerManager, self).__init__(**kwargs)


class FakeFirewallDriver(firewall.NoopFirewallDriver):

    def __init__(self):
        super(FakeFirewallDriver, self).__init__()


class FakeVifDriver(object):

    def __init__(self):
        super(FakeVifDriver, self).__init__()

    def plug(self, instance, vif):
        pass

    def unplug(self, instance, vif):
        pass


class FakeVolumeDriver(object):

    def __init__(self, virtapi):
        super(FakeVolumeDriver, self).__init__()
        self.virtapi = virtapi
        self._initiator = "fake_initiator"

    def attach_volume(self, connection_info, instance, mountpoint):
        pass

    def detach_volume(self, connection_info, instance, mountpoint):
        pass
