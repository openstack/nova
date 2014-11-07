#   Copyright 2014 OpenStack Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import mock
from oslo.config import cfg

from nova.api.openstack import common
from nova.api.openstack.compute.contrib import rescue
from nova.api.openstack import extensions
from nova import compute
import nova.context as context
from nova import test

CONF = cfg.CONF
CONF.import_opt('password_length', 'nova.utils')


class FakeRequest(object):
    def __init__(self, context):
        self.environ = {"nova.context": context}


class ExtendedRescueWithImageTest(test.NoDBTestCase):
    def setUp(self):
        super(ExtendedRescueWithImageTest, self).setUp()
        ext_mgr = extensions.ExtensionManager()
        ext_mgr.extensions = {'os-extended-rescue-with-image': 'fake'}
        self.controller = rescue.RescueController(ext_mgr)

    @mock.patch.object(common, 'get_instance',
                       return_value="instance")
    @mock.patch.object(compute.api.API, "rescue")
    def _make_rescue_request_with_image_ref(self, body, mock_rescue,
                                            mock_get_instance):
        instance = "instance"
        self.controller._get_instance = mock.Mock(return_value=instance)
        fake_context = context.RequestContext('fake', 'fake')
        req = FakeRequest(fake_context)

        self.controller._rescue(req, "id", body)
        rescue_image_ref = body["rescue"].get("rescue_image_ref")
        mock_rescue.assert_called_with(mock.ANY, mock.ANY,
            rescue_password=mock.ANY, rescue_image_ref=rescue_image_ref)

    def test_rescue_with_image_specified(self):
        body = dict(rescue={"rescue_image_ref": "image-ref"})
        self._make_rescue_request_with_image_ref(body)

    def test_rescue_without_image_specified(self):
        body = dict(rescue={})
        self._make_rescue_request_with_image_ref(body)
