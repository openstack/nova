# Copyright (c) 2012 NTT DOCOMO, INC.
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
Bare-Metal DB testcase for BareMetalNode
"""

from nova import exception
from nova.tests.baremetal.db import base
from nova.tests.baremetal.db import utils
from nova.virt.baremetal import db


class BareMetalNodesTestCase(base.BMDBTestCase):

    def _create_nodes(self):
        nodes = [
            utils.new_bm_node(pm_address='0', service_host="host1",
                              memory_mb=100000, cpus=100, local_gb=10000),
            utils.new_bm_node(pm_address='1', service_host="host2",
                              instance_uuid='A',
                              memory_mb=100000, cpus=100, local_gb=10000),
            utils.new_bm_node(pm_address='2', service_host="host2",
                               memory_mb=1000, cpus=1, local_gb=1000),
            utils.new_bm_node(pm_address='3', service_host="host2",
                               memory_mb=1000, cpus=2, local_gb=1000),
            utils.new_bm_node(pm_address='4', service_host="host2",
                               memory_mb=2000, cpus=1, local_gb=1000),
            utils.new_bm_node(pm_address='5', service_host="host2",
                               memory_mb=2000, cpus=2, local_gb=1000),
        ]
        self.ids = []
        for n in nodes:
            ref = db.bm_node_create(self.context, n)
            self.ids.append(ref['id'])

    def test_get_all0(self):
        r = db.bm_node_get_all(self.context)
        self.assertEquals(r, [])

    def test_get_all(self):
        r = db.bm_node_get_all(self.context)
        self.assertEquals(r, [])

        self._create_nodes()

        r = db.bm_node_get_all(self.context)
        self.assertEquals(len(r), 6)

    def test_get(self):
        self._create_nodes()

        r = db.bm_node_get(self.context, self.ids[0])
        self.assertEquals(r['pm_address'], '0')

        r = db.bm_node_get(self.context, self.ids[1])
        self.assertEquals(r['pm_address'], '1')

        self.assertRaises(
              exception.InstanceNotFound,
              db.bm_node_get,
              self.context, -1)

    def test_get_by_service_host(self):
        self._create_nodes()

        r = db.bm_node_get_all(self.context, service_host=None)
        self.assertEquals(len(r), 6)

        r = db.bm_node_get_all(self.context, service_host="host1")
        self.assertEquals(len(r), 1)
        self.assertEquals(r[0]['pm_address'], '0')

        r = db.bm_node_get_all(self.context, service_host="host2")
        self.assertEquals(len(r), 5)
        pmaddrs = [x['pm_address'] for x in r]
        self.assertIn('1', pmaddrs)
        self.assertIn('2', pmaddrs)
        self.assertIn('3', pmaddrs)
        self.assertIn('4', pmaddrs)
        self.assertIn('5', pmaddrs)

        r = db.bm_node_get_all(self.context, service_host="host3")
        self.assertEquals(r, [])

    def test_destroy(self):
        self._create_nodes()

        db.bm_node_destroy(self.context, self.ids[0])

        self.assertRaises(
              exception.InstanceNotFound,
              db.bm_node_get,
              self.context, self.ids[0])

        r = db.bm_node_get_all(self.context)
        self.assertEquals(len(r), 5)

    def test_find_free(self):
        self._create_nodes()
        fn = db.bm_node_find_free(self.context, 'host2')
        self.assertEqual(fn['pm_address'], '2')

        fn = db.bm_node_find_free(self.context, 'host2',
                                  memory_mb=500, cpus=2, local_gb=100)
        self.assertEqual(fn['pm_address'], '3')

        fn = db.bm_node_find_free(self.context, 'host2',
                                  memory_mb=1001, cpus=1, local_gb=1000)
        self.assertEqual(fn['pm_address'], '4')

        fn = db.bm_node_find_free(self.context, 'host2',
                                  memory_mb=2000, cpus=1, local_gb=1000)
        self.assertEqual(fn['pm_address'], '4')

        fn = db.bm_node_find_free(self.context, 'host2',
                                  memory_mb=2000, cpus=2, local_gb=1000)
        self.assertEqual(fn['pm_address'], '5')

        # check memory_mb
        fn = db.bm_node_find_free(self.context, 'host2',
                                  memory_mb=2001, cpus=2, local_gb=1000)
        self.assertTrue(fn is None)

        # check cpus
        fn = db.bm_node_find_free(self.context, 'host2',
                                  memory_mb=2000, cpus=3, local_gb=1000)
        self.assertTrue(fn is None)

        # check local_gb
        fn = db.bm_node_find_free(self.context, 'host2',
                                  memory_mb=2000, cpus=2, local_gb=1001)
        self.assertTrue(fn is None)
