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


class ViewBuilder(common.ViewBuilder):

    _collection_name = 'os-keypairs'
    # TODO(takashin): After v2 and v2.1 is no longer supported,
    # 'type' can always be included in the response.
    _index_params = ('name', 'public_key', 'fingerprint')
    _create_params = _index_params + ('user_id',)
    _show_params = _create_params + ('created_at', 'deleted', 'deleted_at',
                                     'id', 'updated_at')
    _index_params_v2_2 = _index_params + ('type',)
    _show_params_v2_2 = _show_params + ('type',)

    def get_links(self, request, keypairs):
        return self._get_collection_links(request, keypairs,
                                          self._collection_name, 'name')

    # TODO(oomichi): It is necessary to filter a response of keypair with
    # _build_keypair() when v2.1+microversions for implementing consistent
    # behaviors in this keypair resource.
    @staticmethod
    def _build_keypair(keypair, attrs):
        body = {}
        for attr in attrs:
            body[attr] = keypair[attr]
        return body

    def create(self, keypair, private_key=False, key_type=False):
        params = []
        if private_key:
            params.append('private_key')
        # TODO(takashin): After v2 and v2.1 is no longer supported,
        # 'type' can always be included in the response.
        if key_type:
            params.append('type')
        params.extend(self._create_params)

        return {'keypair': self._build_keypair(keypair, params)}

    def index(self, req, key_pairs, key_type=False, links=False):
        keypairs_list = [
            {'keypair': self._build_keypair(
                key_pair,
                self._index_params_v2_2 if key_type else self._index_params)}
                for key_pair in key_pairs]
        keypairs_dict = {'keypairs': keypairs_list}

        if links:
            keypairs_links = self.get_links(req, key_pairs)

            if keypairs_links:
                keypairs_dict['keypairs_links'] = keypairs_links

        return keypairs_dict

    def show(self, keypair, key_type=False):
        return {'keypair': self._build_keypair(
            keypair, self._show_params_v2_2 if key_type
                else self._show_params)}
