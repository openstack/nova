# Copyright 2017 Huawei Technologies Co.,LTD.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from nova.api.openstack import common


class ViewBuilder(common.ViewBuilder):

    def get_links(self, request, server_id, instance_actions):
        collection_name = 'servers/%s/os-instance-actions' % server_id
        return self._get_collection_links(request, instance_actions,
                                          collection_name, 'request_id')
