# Copyright 2016 Mirantis Inc
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
from nova.api.openstack.compute.views import servers


class ViewBuilder(common.ViewBuilder):
    _collection_name = "tags"

    def __init__(self):
        super(ViewBuilder, self).__init__()
        self._server_builder = servers.ViewBuilder()

    def get_location(self, request, server_id, tag_name):
        server_location = self._server_builder._get_href_link(
            request, server_id, "servers")
        return "%s/%s/%s" % (server_location, self._collection_name, tag_name)
