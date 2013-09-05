# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


class VirtAPI(object):
    def instance_update(self, context, instance_uuid, updates):
        """Perform an instance update operation on behalf of a virt driver
        :param context: security context
        :param instance_uuid: uuid of the instance to be updated
        :param updates: dict of attribute=value pairs to change

        Returns: orig_instance, new_instance
        """
        raise NotImplementedError()

    def aggregate_get_by_host(self, context, host, key=None):
        """Get a list of aggregates to which the specified host belongs
        :param context: security context
        :param host: the host for which aggregates should be returned
        :param key: optionally filter by hosts with the given metadata key
        """
        raise NotImplementedError()

    def aggregate_metadata_add(self, context, aggregate, metadata,
                               set_delete=False):
        """Add/update metadata for specified aggregate
        :param context: security context
        :param aggregate: aggregate on which to update metadata
        :param metadata: dict of metadata to add/update
        :param set_delete: if True, only add
        """
        raise NotImplementedError()

    def aggregate_metadata_delete(self, context, aggregate, key):
        """Delete the given metadata key from specified aggregate
        :param context: security context
        :param aggregate: aggregate from which to delete metadata
        :param key: metadata key to delete
        """
        raise NotImplementedError()

    def security_group_get_by_instance(self, context, instance):
        """Get the security group for a specified instance
        :param context: security context
        :param instance: instance defining the security group we want
        """
        raise NotImplementedError()

    def security_group_rule_get_by_security_group(self, context,
                                                  security_group):
        """Get the rules associated with a specified security group
        :param context: security context
        :param security_group: the security group for which the rules
                               should be returned
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

    def instance_type_get(self, context, instance_type_id):
        """Get information about an instance type
        :param context: security context
        :param instance_type_id: the id of the instance type in question
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

    def block_device_mapping_update(self, context, bdm_id, bdm_values):
        """Update the databse for the passed block device mapping
        :param context: security context
        :param bdm: the block device mapping dict
        """
        raise NotImplementedError()
