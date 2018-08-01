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

import os
from oslotest import output

import wsgi_intercept

from gabbi import driver

from nova.tests.functional.api.openstack.placement.fixtures import capture
# TODO(cdent): This whitespace blight will go away post extraction.
from nova.tests.functional.api.openstack.placement.fixtures \
        import gabbits as fixtures

# Check that wsgi application response headers are always
# native str.
wsgi_intercept.STRICT_RESPONSE_HEADERS = True
TESTS_DIR = 'gabbits'


def load_tests(loader, tests, pattern):
    """Provide a TestSuite to the discovery process."""
    test_dir = os.path.join(os.path.dirname(__file__), TESTS_DIR)
    # These inner fixtures provide per test request output and log
    # capture, for cleaner results reporting.
    inner_fixtures = [
        output.CaptureOutput,
        capture.Logging,
    ]
    return driver.build_tests(test_dir, loader, host=None,
                              test_loader_name=__name__,
                              intercept=fixtures.setup_app,
                              inner_fixtures=inner_fixtures,
                              fixture_module=fixtures)
