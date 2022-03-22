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
    _collection_name = 'shares'

    def __init__(self):
        super(ViewBuilder, self).__init__()
        self._server_builder = servers.ViewBuilder()

    def _list_view(self, db_shares):
        shares = {'shares': []}
        for db_share in db_shares:
            share = {
                'share_id': db_share.share_id,
                'status': db_share.status,
                'tag': db_share.tag,
            }
            shares['shares'].append(share)
        return shares

    def _show_view(self, context, db_share):
        share = {'share': {
            'share_id': db_share.share_id,
            'status': db_share.status,
            'tag': db_share.tag,
        }}

        if context.is_admin:
            share['share']['export_location'] = db_share.export_location
            share['share']['uuid'] = db_share.uuid

        return share
