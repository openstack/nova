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

import mock

from nova import cache_utils
from nova import test


class TestOsloCache(test.NoDBTestCase):
    def test_get_default_cache_region(self):
        region = cache_utils._get_default_cache_region(expiration_time=60)
        self.assertEqual(60, region.expiration_time)
        self.assertIsNotNone(region)

    def test_get_default_cache_region_default_expiration_time(self):
        region = cache_utils._get_default_cache_region(expiration_time=0)
        # default oslo.cache expiration_time value 600 was taken
        self.assertEqual(600, region.expiration_time)
        self.assertIsNotNone(region)

    @mock.patch('dogpile.cache.region.CacheRegion.configure')
    def test_get_custom_cache_region(self, mock_cacheregion):
        self.assertRaises(RuntimeError,
                          cache_utils._get_custom_cache_region)
        self.assertIsNotNone(
                cache_utils._get_custom_cache_region(
                        backend='oslo_cache.dict'))
        self.assertIsNotNone(
                cache_utils._get_custom_cache_region(
                        backend='dogpile.cache.memcached',
                        url=['localhost:11211']))
        mock_cacheregion.assert_has_calls(
                [mock.call('oslo_cache.dict',
                           arguments={'expiration_time': 604800},
                           expiration_time=604800),
                 mock.call('dogpile.cache.memcached',
                           arguments={'url': ['localhost:11211']},
                           expiration_time=604800)]
        )

    @mock.patch('dogpile.cache.region.CacheRegion.configure')
    def test_get_memcached_client(self, mock_cacheregion):
        self.flags(group='cache', enabled=True)
        self.flags(group='cache', memcache_servers=['localhost:11211'])
        self.assertIsNotNone(
                cache_utils.get_memcached_client(expiration_time=60))

        methods_called = [a[0] for n, a, k in mock_cacheregion.mock_calls]
        self.assertEqual(['dogpile.cache.null'], methods_called)
