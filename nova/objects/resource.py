#    Copyright 2019 Intel Inc.
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

from oslo_serialization import jsonutils

from nova.db import api as db
from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
class ResourceMetadata(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = "1.0"

    # This is parent object of specific resources.
    # And it's used to be a object field of Resource,
    # that is to say Resource.metadata.

    def __eq__(self, other):
        return base.all_things_equal(self, other)

    def __ne__(self, other):
        return not (self == other)


@base.NovaObjectRegistry.register
class Resource(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = "1.0"

    fields = {
        # UUID of resource provider
        'provider_uuid': fields.UUIDField(),
        # resource class of the Resource
        'resource_class': fields.ResourceClassField(),
        # identifier is used to identify resource, it is up to virt drivers
        # for mdev, it will be a UUID, for vpmem, it's backend namespace name
        'identifier': fields.StringField(),
        # metadata is used to contain virt driver specific resource info
        'metadata': fields.ObjectField('ResourceMetadata', subclasses=True),
    }

    def __eq__(self, other):
        return base.all_things_equal(self, other)

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        metadata = self.metadata if 'metadata' in self else None
        return hash((self.provider_uuid, self.resource_class,
                     self.identifier, metadata))


@base.NovaObjectRegistry.register
class ResourceList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = "1.0"

    fields = {
        'objects': fields.ListOfObjectsField('Resource'),
    }

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_extra = db.instance_extra_get_by_instance_uuid(
                context, instance_uuid, columns=['resources'])
        if not db_extra or db_extra['resources'] is None:
            return None

        primitive = jsonutils.loads(db_extra['resources'])
        resources = cls.obj_from_primitive(primitive)
        return resources


@base.NovaObjectRegistry.register
class LibvirtVPMEMDevice(ResourceMetadata):
    # Version 1.0: Initial version
    VERSION = "1.0"

    fields = {
        # This is configured in file, used to generate resource class name
        # CUSTOM_PMEM_NAMESPACE_$LABEL
        'label': fields.StringField(),
        # Backend pmem namespace's name
        'name': fields.StringField(),
        # Backend pmem namespace's size
        'size': fields.IntegerField(),
        # Backend device path
        'devpath': fields.StringField(),
        # Backend pmem namespace's alignment
        'align': fields.IntegerField(),
    }

    def __hash__(self):
        # Be sure all fields are set before using hash method
        return hash((self.label, self.name, self.size,
                     self.devpath, self.align))
