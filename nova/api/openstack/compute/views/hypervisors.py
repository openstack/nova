# Copyright 2016 Kylin Cloud
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
    _collection_name = "os-hypervisors"

    def get_links(self, request, hypervisors, detail=False):
        coll_name = (self._collection_name + '/detail' if detail else
                     self._collection_name)
        return self._get_collection_links(request, hypervisors, coll_name,
                                          'id')
