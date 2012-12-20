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

from nova.virt.baremetal import baremetal_states


class NodeDriver(object):

    def define_vars(self, instance, network_info, block_device_info):
        raise NotImplementedError()

    def create_image(self, var, context, image_meta, node, instance,
                     injected_files=None, admin_password=None):
        raise NotImplementedError()

    def destroy_images(self, var, context, node, instance):
        raise NotImplementedError()

    def activate_bootloader(self, var, context, node, instance, image_meta):
        raise NotImplementedError()

    def deactivate_bootloader(self, var, context, node, instance):
        raise NotImplementedError()

    def activate_node(self, var, context, node, instance):
        """For operations after power on."""
        raise NotImplementedError()

    def deactivate_node(self, var, context, node, instance):
        """For operations before power off."""
        raise NotImplementedError()

    def get_console_output(self, node, instance):
        raise NotImplementedError()


class PowerManager(object):

    def __init__(self, node):
        pass

    def activate_node(self):
        return baremetal_states.ACTIVE

    def reboot_node(self):
        return baremetal_states.ACTIVE

    def deactivate_node(self):
        return baremetal_states.DELETED

    def is_power_on(self):
        """Returns True or False according as the node's power state"""
        return True

    # TODO(NTTdocomo): split out console methods to its own class
    def start_console(self):
        pass

    def stop_console(self):
        pass
