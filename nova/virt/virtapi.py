#    Copyright 2012 IBM Corp.
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

import contextlib


class VirtAPI(object):
    def instance_update(self, context, instance_uuid, updates):
        """Perform an instance update operation on behalf of a virt driver
        :param context: security context
        :param instance_uuid: uuid of the instance to be updated
        :param updates: dict of attribute=value pairs to change

        Returns: orig_instance, new_instance
        """
        raise NotImplementedError()

    def provider_fw_rule_get_all(self, context):
        """Get the provider firewall rules
        :param context: security context
        """
        raise NotImplementedError()

    def agent_build_get_by_triple(self, context, hypervisor, os, architecture):
        """Get information about the available agent builds for a given
        hypervisor, os, and architecture
        :param context: security context
        :param hypervisor: agent hypervisor type
        :param os: agent operating system type
        :param architecture: agent architecture
        """
        raise NotImplementedError()

    def block_device_mapping_get_all_by_instance(self, context, instance,
                                                 legacy=True):
        """Get block device mappings for an instance
        :param context: security context
        :param instance: the instance we're getting bdms for
        :param legacy: get bdm info in legacy format (or not)
        """
        raise NotImplementedError()

    @contextlib.contextmanager
    def wait_for_instance_event(self, instance, event_names, deadline=300,
                                error_callback=None):
        raise NotImplementedError()
