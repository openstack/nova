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
from oslo_utils.fixture import uuidsentinel as uuids

from nova import objects
from nova.scheduler.filters import isolated_hosts_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestIsolatedHostsFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestIsolatedHostsFilter, self).setUp()
        self.filt_cls = isolated_hosts_filter.IsolatedHostsFilter()

    def _do_test_isolated_hosts(self, host_in_list, image_in_list,
                            set_flags=True,
                            restrict_isolated_hosts_to_isolated_images=True):
        if set_flags:
            self.flags(isolated_images=[uuids.image_ref],
                       isolated_hosts=['isolated_host'],
                       restrict_isolated_hosts_to_isolated_images=
                       restrict_isolated_hosts_to_isolated_images,
                       group='filter_scheduler')
        host_name = 'isolated_host' if host_in_list else 'free_host'
        image_ref = uuids.image_ref if image_in_list else uuids.fake_image_ref
        spec_obj = objects.RequestSpec(image=objects.ImageMeta(id=image_ref))
        host = fakes.FakeHostState(host_name, 'node', {})
        return self.filt_cls.host_passes(host, spec_obj)

    def test_isolated_hosts_fails_isolated_on_non_isolated(self):
        self.assertFalse(self._do_test_isolated_hosts(False, True))

    def test_isolated_hosts_fails_non_isolated_on_isolated(self):
        self.assertFalse(self._do_test_isolated_hosts(True, False))

    def test_isolated_hosts_passes_isolated_on_isolated(self):
        self.assertTrue(self._do_test_isolated_hosts(True, True))

    def test_isolated_hosts_passes_non_isolated_on_non_isolated(self):
        self.assertTrue(self._do_test_isolated_hosts(False, False))

    def test_isolated_hosts_no_config(self):
        # If there are no hosts nor isolated images in the config, it should
        # not filter at all. This is the default config.
        self.assertTrue(self._do_test_isolated_hosts(False, True, False))
        self.assertTrue(self._do_test_isolated_hosts(True, False, False))
        self.assertTrue(self._do_test_isolated_hosts(True, True, False))
        self.assertTrue(self._do_test_isolated_hosts(False, False, False))

    def test_isolated_hosts_no_hosts_config(self):
        self.flags(isolated_images=[uuids.image_ref], group='filter_scheduler')
        # If there are no hosts in the config, it should only filter out
        # images that are listed
        self.assertFalse(self._do_test_isolated_hosts(False, True, False))
        self.assertTrue(self._do_test_isolated_hosts(True, False, False))
        self.assertFalse(self._do_test_isolated_hosts(True, True, False))
        self.assertTrue(self._do_test_isolated_hosts(False, False, False))

    def test_isolated_hosts_no_images_config(self):
        self.flags(isolated_hosts=['isolated_host'], group='filter_scheduler')
        # If there are no images in the config, it should only filter out
        # isolated_hosts
        self.assertTrue(self._do_test_isolated_hosts(False, True, False))
        self.assertFalse(self._do_test_isolated_hosts(True, False, False))
        self.assertFalse(self._do_test_isolated_hosts(True, True, False))
        self.assertTrue(self._do_test_isolated_hosts(False, False, False))

    def test_isolated_hosts_less_restrictive(self):
        # If there are isolated hosts and non isolated images
        self.assertTrue(self._do_test_isolated_hosts(True, False, True, False))
        # If there are isolated hosts and isolated images
        self.assertTrue(self._do_test_isolated_hosts(True, True, True, False))
        # If there are non isolated hosts and non isolated images
        self.assertTrue(self._do_test_isolated_hosts(False, False, True,
                                                     False))
        # If there are non isolated hosts and isolated images
        self.assertFalse(self._do_test_isolated_hosts(False, True, True,
                                                      False))
