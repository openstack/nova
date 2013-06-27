# Copyright 2012 Nebula, Inc.
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

from lxml import etree
import webob

from nova.api.openstack.compute.plugins.v3 import flavor_disabled
from nova.compute import flavors
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes

FAKE_FLAVORS = {
    'flavor 1': {
        "flavorid": '1',
        "name": 'flavor 1',
        "memory_mb": '256',
        "root_gb": '10',
        "disabled": False,
    },
    'flavor 2': {
        "flavorid": '2',
        "name": 'flavor 2',
        "memory_mb": '512',
        "root_gb": '20',
        "disabled": True,
    },
}


def fake_flavor_get_by_flavor_id(flavorid):
    return FAKE_FLAVORS['flavor %s' % flavorid]


def fake_flavor_get_all(*args, **kwargs):
    return FAKE_FLAVORS


class FlavorDisabledTest(test.TestCase):
    content_type = 'application/json'
    prefix = '%s:' % flavor_disabled.FlavorDisabled.alias

    def setUp(self):
        super(FlavorDisabledTest, self).setUp()
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(flavors, "get_all_flavors",
                       fake_flavor_get_all)
        self.stubs.Set(flavors,
                       "get_flavor_by_flavor_id",
                       fake_flavor_get_by_flavor_id)

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        app = fakes.wsgi_app_v3(init_only=('servers', 'flavors',
                                           'os-flavor-disabled'))
        return req.get_response(app)

    def _get_flavor(self, body):
        return jsonutils.loads(body).get('flavor')

    def _get_flavors(self, body):
        return jsonutils.loads(body).get('flavors')

    def assertFlavorDisabled(self, flavor, disabled):
        self.assertEqual(str(flavor.get('%sdisabled' % self.prefix)), disabled)

    def test_show(self):
        res = self._make_request('/v3/flavors/1')
        self.assertEqual(res.status_int, 200, res.body)
        self.assertFlavorDisabled(self._get_flavor(res.body), 'False')

    def test_detail(self):
        res = self._make_request('/v3/flavors/detail')

        self.assertEqual(res.status_int, 200, res.body)
        flavors = self._get_flavors(res.body)
        self.assertFlavorDisabled(flavors[0], 'False')
        self.assertFlavorDisabled(flavors[1], 'True')


class FlavorDisabledXmlTest(FlavorDisabledTest):
    content_type = 'application/xml'
    prefix = '{%s}' % flavor_disabled.FlavorDisabled.namespace

    def _get_flavor(self, body):
        return etree.XML(body)

    def _get_flavors(self, body):
        return etree.XML(body).getchildren()
