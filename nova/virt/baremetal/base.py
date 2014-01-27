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

from nova.virt.baremetal import baremetal_states


class NodeDriver(object):

    def __init__(self, virtapi):
        self.virtapi = virtapi

    def cache_images(self, context, node, instance, **kwargs):
        raise NotImplementedError()

    def destroy_images(self, context, node, instance):
        raise NotImplementedError()

    def activate_bootloader(self, context, node, instance, **kwargs):
        raise NotImplementedError()

    def deactivate_bootloader(self, context, node, instance):
        raise NotImplementedError()

    def activate_node(self, context, node, instance):
        """For operations after power on."""
        raise NotImplementedError()

    def deactivate_node(self, context, node, instance):
        """For operations before power off."""
        raise NotImplementedError()

    def get_console_output(self, node, instance):
        raise NotImplementedError()

    def dhcp_options_for_instance(self, instance):
        """Optional override to return the DHCP options to use for instance.

        If no DHCP options are needed, this should not be overridden or None
        should be returned.
        """
        return None


class PowerManager(object):

    def __init__(self, **kwargs):
        self.state = baremetal_states.DELETED
        pass

    def activate_node(self):
        self.state = baremetal_states.ACTIVE
        return self.state

    def reboot_node(self):
        self.state = baremetal_states.ACTIVE
        return self.state

    def deactivate_node(self):
        self.state = baremetal_states.DELETED
        return self.state

    def is_power_on(self):
        """Returns True or False according as the node's power state."""
        return True

    # TODO(NTTdocomo): split out console methods to its own class
    def start_console(self):
        pass

    def stop_console(self):
        pass
