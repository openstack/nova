# Copyright 2011 Eldar Nugaev
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

import json
import unittest

from lxml import etree

from nova.api.openstack import v2
from nova.api.openstack.v2.contrib import server_diagnostics
from nova.api.openstack.v2 import extensions
from nova.api.openstack import wsgi
import nova.compute
from nova import test
from nova.tests.api.openstack import fakes
import nova.utils


def fake_get_diagnostics(self, _context, instance_uuid):
    return {'data': 'Some diagnostic info'}


def fake_instance_get(self, _context, instance_uuid):
    return {'uuid': instance_uuid}


class ServerDiagnosticsTest(test.TestCase):

    def setUp(self):
        super(ServerDiagnosticsTest, self).setUp()
        self.flags(allow_admin_api=True)
        self.flags(verbose=True)
        self.stubs.Set(nova.compute.API, 'get_diagnostics',
                       fake_get_diagnostics)
        self.stubs.Set(nova.compute.API, 'get', fake_instance_get)
        self.compute_api = nova.compute.API()

        self.router = v2.APIRouter()
        ext_middleware = extensions.ExtensionMiddleware(self.router)
        self.app = wsgi.LazySerializationMiddleware(ext_middleware)

    def test_get_diagnostics(self):
        uuid = nova.utils.gen_uuid()
        req = fakes.HTTPRequest.blank('/fake/servers/%s/diagnostics' % uuid)
        res = req.get_response(self.app)
        output = json.loads(res.body)
        self.assertEqual(output, {'data': 'Some diagnostic info'})


class TestServerDiagnosticsXMLSerializer(unittest.TestCase):
    namespace = wsgi.XMLNS_V11

    def _tag(self, elem):
        tagname = elem.tag
        self.assertEqual(tagname[0], '{')
        tmp = tagname.partition('}')
        namespace = tmp[0][1:]
        self.assertEqual(namespace, self.namespace)
        return tmp[2]

    def test_index_serializer(self):
        serializer = server_diagnostics.ServerDiagnosticsTemplate()
        exemplar = dict(diag1='foo', diag2='bar')
        text = serializer.serialize(exemplar)

        print text
        tree = etree.fromstring(text)

        self.assertEqual('diagnostics', self._tag(tree))
        self.assertEqual(len(tree), len(exemplar))
        for child in tree:
            tag = self._tag(child)
            self.assertTrue(tag in exemplar)
            self.assertEqual(child.text, exemplar[tag])
