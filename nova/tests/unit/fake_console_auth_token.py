#    Copyright 2016 Intel Corp.
#    Copyright 2016 Hewlett Packard Enterprise Development Company LP
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
from oslo_utils.fixture import uuidsentinel

from nova import utils


fake_token = uuidsentinel.token
fake_token_hash = utils.get_sha256_str(fake_token)
fake_instance_uuid = uuidsentinel.instance
fake_token_dict = {
    'created_at': None,
    'updated_at': None,
    'id': 123,
    'token_hash': fake_token_hash,
    'console_type': 'fake-type',
    'host': 'fake-host',
    'port': 1000,
    'internal_access_path': 'fake-path',
    'instance_uuid': fake_instance_uuid,
    'expires': 100,
    'access_url_base': 'http://fake.url.fake/root.html'
    }
