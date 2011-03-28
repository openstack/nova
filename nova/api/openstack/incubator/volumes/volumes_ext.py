# Copyright 2011 Justin Santa Barbara
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

from nova.api.openstack import extensions
from nova.api.openstack.incubator.volumes import volumes
from nova.api.openstack.incubator.volumes import volume_attachments


class VolumesExtension(extensions.ExtensionDescriptor):
    def get_name(self):
        return "Volumes"

    def get_alias(self):
        return "VOLUMES"

    def get_description(self):
        return "Volumes support"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/volumes/api/v1.1"

    def get_updated(self):
        return "2011-03-25T00:00:00+00:00"

    def get_resources(self):
        resources = []

        # NOTE(justinsb): No way to provide singular name ('volume')
        # Does this matter?
        res = extensions.ResourceExtension('volumes',
                                           volumes.Controller(),
                                           collection_actions={'detail': 'GET'}
                                          )
        resources.append(res)

        res = extensions.ResourceExtension('volume_attachments',
                                           volume_attachments.Controller(),
                                           parent=dict(
                                                member_name='server',
                                                collection_name='servers'))
        resources.append(res)

        return resources
