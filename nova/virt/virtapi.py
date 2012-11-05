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


from nova import db


class VirtAPI(object):
    def instance_update(self, context, instance_uuid, updates):
        """Perform an instance update operation on behalf of a virt driver
        :param context: security context
        :param instance_uuid: uuid of the instance to be updated
        :param updates: dict of attribute=value pairs to change

        Returns: orig_instance, new_instance
        """
        raise NotImplementedError()

    def instance_get_by_uuid(self, context, instance_uuid):
        """Look up an instance by uuid
        :param context: security context
        :param instance_uuid: uuid of the instance to be fetched
        """
        raise NotImplementedError()

    def instance_get_all_by_host(self, context, host):
        """Find all instances on a given host
        :param context: security context
        :param host: host running instances to be returned
        """
        raise NotImplementedError()

    def aggregate_get_by_host(self, context, host, key=None):
        """Get a list of aggregates to which the specified host belongs
        :param context: security context
        :param host: the host for which aggregates should be returned
        :param key: optionally filter by hosts with the given metadata key
        """
        raise NotImplementedError()

    def aggregate_metadata_get(self, context, aggregate_id):
        """Get metadata for the specified aggregate
        :param context: security context
        :param aggregate_id: id of aggregate for which metadata is to
                             be returned
        """
        raise NotImplementedError()

    def aggregate_metadata_add(self, context, aggregate_id, metadata,
                               set_delete=False):
        """Add/update metadata for specified aggregate
        :param context: security context
        :param aggregate_id: id of aggregate on which to update metadata
        :param metadata: dict of metadata to add/update
        :param set_delete: if True, only add
        """
        raise NotImplementedError()

    def aggregate_metadata_delete(self, context, aggregate_id, key):
        """Delete the given metadata key from specified aggregate
        :param context: security context
        :param aggregate_id: id of aggregate from which to delete metadata
        :param key: metadata key to delete
        """
        raise NotImplementedError()
