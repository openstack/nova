# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2010 OpenStack Foundation
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

"""
Test WSGI basics and provide some helper functions for other WSGI tests.
"""

import tempfile

import routes
import webob

from nova.api import wsgi
import nova.exception
from nova import test


class TestRouter(test.NoDBTestCase):

    def test_router(self):

        class Application(wsgi.Application):
            """Test application to call from router."""

            def __call__(self, environ, start_response):
                start_response("200", [])
                return ['Router result']

        class Router(wsgi.Router):
            """Test router."""

            def __init__(self):
                mapper = routes.Mapper()
                mapper.connect("/test", controller=Application())
                super(Router, self).__init__(mapper)

        result = webob.Request.blank('/test').get_response(Router())
        self.assertEqual(result.body, "Router result")
        result = webob.Request.blank('/bad').get_response(Router())
        self.assertNotEqual(result.body, "Router result")


class TestLoaderNothingExists(test.NoDBTestCase):
    """Loader tests where os.path.exists always returns False."""

    def setUp(self):
        super(TestLoaderNothingExists, self).setUp()
        self.stub_out('os.path.exists', lambda _: False)

    def test_relpath_config_not_found(self):
        self.flags(api_paste_config='api-paste.ini', group='wsgi')
        self.assertRaises(
            nova.exception.ConfigNotFound,
            wsgi.Loader,
        )

    def test_asbpath_config_not_found(self):
        self.flags(api_paste_config='/etc/nova/api-paste.ini', group='wsgi')
        self.assertRaises(
            nova.exception.ConfigNotFound,
            wsgi.Loader,
        )


class TestLoaderNormalFilesystem(test.NoDBTestCase):
    """Loader tests with normal filesystem (unmodified os.path module)."""

    _paste_config = """
[app:test_app]
use = egg:Paste#static
document_root = /tmp
    """

    def setUp(self):
        super(TestLoaderNormalFilesystem, self).setUp()
        self.config = tempfile.NamedTemporaryFile(mode="w+t")
        self.config.write(self._paste_config.lstrip())
        self.config.seek(0)
        self.config.flush()
        self.loader = wsgi.Loader(self.config.name)

    def test_config_found(self):
        self.assertEqual(self.config.name, self.loader.config_path)

    def test_app_not_found(self):
        self.assertRaises(
            nova.exception.PasteAppNotFound,
            self.loader.load_app,
            "nonexistent app",
        )

    def test_app_found(self):
        url_parser = self.loader.load_app("test_app")
        self.assertEqual("/tmp", url_parser.directory)

    def tearDown(self):
        self.config.close()
        super(TestLoaderNormalFilesystem, self).tearDown()
