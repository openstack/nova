# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Red Hat, Inc.
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

from nova.api.openstack import common


class ViewBuilder(common.ViewBuilder):

    def show(self, request, volume_type, brief=False):
        """Trim away extraneous volume type attributes."""
        trimmed = dict(id=volume_type.get('id'),
                          name=volume_type.get('name'),
                          extra_specs=volume_type.get('extra_specs'))
        return trimmed if brief else dict(volume_type=trimmed)

    def index(self, request, volume_types):
        """Index over trimmed volume types"""
        volume_types_list = [self.show(request, volume_type, True)
                             for volume_type in volume_types]
        return dict(volume_types=volume_types_list)
