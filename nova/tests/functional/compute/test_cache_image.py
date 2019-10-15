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

from nova import context
from nova import objects
from nova import test
from nova.tests.unit import fake_notifier


class ImageCacheTest(test.TestCase):
    NUMBER_OF_CELLS = 2

    def setUp(self):
        super(ImageCacheTest, self).setUp()

        self.flags(compute_driver='fake.FakeDriverWithCaching')

        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)
        self.context = context.get_admin_context()

        self.conductor = self.start_service('conductor')
        self.compute1 = self.start_service('compute', host='compute1')
        self.compute2 = self.start_service('compute', host='compute2')
        self.compute3 = self.start_service('compute', host='compute3',
                                           cell='cell2')
        self.compute4 = self.start_service('compute', host='compute4',
                                           cell='cell2')
        self.compute5 = self.start_service('compute', host='compute5',
                                           cell='cell2')

        cell2 = self.cell_mappings['cell2']
        with context.target_cell(self.context, cell2) as cctxt:
            srv = objects.Service.get_by_compute_host(cctxt, 'compute5')
            srv.forced_down = True
            srv.save()

    def test_cache_image(self):
        """Test caching images by injecting the request directly to
        the conductor service and making sure it fans out and calls
        the expected nodes.
        """

        aggregate = objects.Aggregate(name='test',
                                      uuid=uuids.aggregate,
                                      id=1,
                                      hosts=['compute1', 'compute3',
                                             'compute4', 'compute5'])
        self.conductor.compute_task_mgr.cache_images(
            self.context, aggregate, ['an-image'])

        # NOTE(danms): We expect only three image cache attempts because
        # compute5 is marked as forced-down and compute2 is not in the
        # requested aggregate.
        for host in ['compute1', 'compute3', 'compute4']:
            mgr = getattr(self, host)
            self.assertEqual(set(['an-image']), mgr.driver.cached_images)
        for host in ['compute2', 'compute5']:
            mgr = getattr(self, host)
            self.assertEqual(set(), mgr.driver.cached_images)

        fake_notifier.wait_for_versioned_notifications(
            'aggregate.cache_images.start')
        fake_notifier.wait_for_versioned_notifications(
            'aggregate.cache_images.end')
