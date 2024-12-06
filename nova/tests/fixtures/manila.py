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

import fixtures
import nova
from oslo_config import cfg
from oslo_log import log as logging


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class ManilaShare():
    def __init__(self, share_id, proto="NFS"):
        self.id = share_id
        self.size = 1
        self.availability_zone = "nova"
        self.created_at = "2015-09-18T10:25:24.000000"
        self.status = "available"
        self.name = "share_London"
        self.description = "My custom share London"
        self.project_id = "6a6a9c9eee154e9cb8cec487b98d36ab"
        self.snapshot_id = None
        self.share_network_id = "713df749-aac0-4a54-af52-10f6c991e80c"
        self.share_protocol = proto
        self.metadata = {"project": "my_app", "aim": "doc"}
        self.share_type = "25747776-08e5-494f-ab40-a64b9d20d8f7"
        self.volume_type = "default"
        self.is_public = True


class ManilaAccess():
    def __init__(self, access_type="ip"):
        self.access_level = "rw"
        self.state = "active"
        self.id = "507bf114-36f2-4f56-8cf4-857985ca87c1"
        if access_type == "ip":
            self.access_type = "ip"
            self.access_to = "192.168.0.1"
            self.access_key = None
        elif access_type == "cephx":
            self.access_type = "cephx"
            self.access_to = "nova"
            self.access_key = "mykey"


class ManilaFixture(fixtures.Fixture):
    """Fixture that mocks Manila APIs used by nova/share/manila.py"""

    def setUp(self):
        super().setUp()
        self.share_access = set()
        self.mock_get = self.useFixture(fixtures.MockPatch(
            'nova.share.manila.API.get',
            side_effect=self.fake_get)).mock
        self.mock_get_access = self.useFixture(fixtures.MockPatch(
            'nova.share.manila.API.get_access',
            side_effect=self.fake_get_access)).mock
        self.mock_allow = self.useFixture(fixtures.MockPatch(
            'nova.share.manila.API.allow',
            side_effect=self.fake_allow)).mock
        self.mock_deny = self.useFixture(fixtures.MockPatch(
            'nova.share.manila.API.deny',
            side_effect=self.fake_deny)).mock

    def fake_get(self, context, share_id):
        manila_share = ManilaShare(share_id)
        export_location = "10.0.0.50:/mnt/foo"
        return nova.share.manila.Share.from_manila_share(
            manila_share, export_location
        )

    def fake_get_share_status_error(self, context, share_id):
        manila_share = ManilaShare(share_id)
        manila_share.status = "error"
        export_location = "10.0.0.50:/mnt/foo"
        return nova.share.manila.Share.from_manila_share(
            manila_share, export_location
        )

    def fake_get_share_export_location_missing(self, context, share_id):
        manila_share = ManilaShare(share_id)
        export_location = None
        return nova.share.manila.Share.from_manila_share(
            manila_share, export_location
        )

    def fake_get_share_unknown_protocol(self, context, share_id):
        manila_share = ManilaShare(share_id)
        manila_share.share_protocol = "CIFS"
        export_location = "10.0.0.50:/mnt/foo"
        return nova.share.manila.Share.from_manila_share(
            manila_share, export_location
        )

    def fake_get_cephfs(self, context, share_id):
        manila_share = ManilaShare(share_id, "CEPHFS")
        export_location = "10.0.0.50:/mnt/foo"
        return nova.share.manila.Share.from_manila_share(
            manila_share, export_location
        )

    def fake_get_access(self, context, share_id, access_type, access_to):
        if share_id not in self.share_access:
            return None
        else:
            access = ManilaAccess()
            return nova.share.manila.Access.from_manila_access(access)

    def fake_get_access_cephfs(
        self, context, share_id, access_type, access_to
    ):
        access = ManilaAccess(access_type="cephx")
        return access

    def fake_allow(
        self, context, share_id, access_type, access_to, access_level
    ):
        self.share_access.add(share_id)
        self.fake_get_access(context, share_id, access_type, access_to)

    def fake_deny(self, context, share_id, access_type, access_to):
        self.share_access.discard(share_id)
        return 202
