#    Copyright 2022 Red Hat, inc.
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

import os
from unittest import mock
import uuid

import fixtures
from oslo_config import cfg
from oslo_utils.fixture import uuidsentinel as uuids
import testtools

from nova import exception
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.virt import node

CONF = cfg.CONF


# NOTE(danms): We do not inherit from test.TestCase because we need
# our node methods not stubbed out in order to exercise them.
class TestNodeIdentity(testtools.TestCase):
    def flags(self, **kw):
        """Override flag variables for a test."""
        group = kw.pop('group', None)
        for k, v in kw.items():
            CONF.set_override(k, v, group)

    def setUp(self):
        super().setUp()
        self.useFixture(nova_fixtures.ConfFixture(CONF))
        self.tempdir = self.useFixture(fixtures.TempDir()).path
        self.identity_file = os.path.join(self.tempdir, node.COMPUTE_ID_FILE)
        self.fake_config_files = ['%s/etc/nova.conf' % self.tempdir,
                                  '%s/etc/nova/nova.conf' % self.tempdir,
                                  '%s/opt/etc/nova/nova.conf' % self.tempdir]
        for fn in self.fake_config_files:
            os.makedirs(os.path.dirname(fn))
        self.flags(state_path=self.tempdir,
                   config_file=self.fake_config_files)
        node.LOCAL_NODE_UUID = None

    def test_generate_local_node_uuid(self):
        node_uuid = uuids.node
        node.write_local_node_uuid(node_uuid)

        e = self.assertRaises(exception.InvalidNodeConfiguration,
                              node.write_local_node_uuid, 'anything')
        self.assertIn(
            'Identity file %s appeared unexpectedly' % self.identity_file,
            str(e))

    def test_generate_local_node_uuid_unexpected_open_fail(self):
        with mock.patch('builtins.open') as mock_open:
            mock_open.side_effect = IndexError()
            e = self.assertRaises(exception.InvalidNodeConfiguration,
                                  node.write_local_node_uuid, 'foo')
            self.assertIn('Unable to write uuid to %s' % (
                self.identity_file), str(e))

    def test_generate_local_node_uuid_unexpected_write_fail(self):
        with mock.patch('builtins.open') as mock_open:
            mock_write = mock_open.return_value.__enter__.return_value.write
            mock_write.side_effect = IndexError()
            e = self.assertRaises(exception.InvalidNodeConfiguration,
                                  node.write_local_node_uuid, 'foo')
            self.assertIn('Unable to write uuid to %s' % (
                self.identity_file), str(e))

    def test_get_local_node_uuid_simple_exists(self):
        node_uuid = uuids.node
        with test.patch_open('%s/etc/nova/compute_id' % self.tempdir,
                             node_uuid):
            self.assertEqual(node_uuid, node.get_local_node_uuid())

    def test_get_local_node_uuid_simple_exists_whitespace(self):
        node_uuid = uuids.node
        # Make sure we strip whitespace from the file contents
        with test.patch_open('%s/etc/nova/compute_id' % self.tempdir,
                             ' %s \n' % node_uuid):
            self.assertEqual(node_uuid, node.get_local_node_uuid())

    def test_get_local_node_uuid_simple_generate(self):
        self.assertIsNone(node.LOCAL_NODE_UUID)
        node_uuid1 = node.get_local_node_uuid()
        self.assertEqual(node_uuid1, node.LOCAL_NODE_UUID)
        node_uuid2 = node.get_local_node_uuid()
        self.assertEqual(node_uuid2, node.LOCAL_NODE_UUID)

        # Make sure we got the same thing each time, and that it's a
        # valid uuid. Since we provided no uuid, it must have been
        # generated the first time and read/returned the second.
        self.assertEqual(node_uuid1, node_uuid2)
        uuid.UUID(node_uuid1)

        # Try to read it directly to make sure the file was really
        # created and with the right value.
        self.assertEqual(node_uuid1, node.read_local_node_uuid())

    def test_get_local_node_uuid_two(self):
        node_uuid = uuids.node

        # Write the uuid to two of our locations
        for cf in (self.fake_config_files[0], self.fake_config_files[1]):
            open(os.path.join(os.path.dirname(cf),
                              node.COMPUTE_ID_FILE), 'w').write(node_uuid)

        # Make sure we got the expected uuid and that no exceptions
        # were raised about the files disagreeing
        self.assertEqual(node_uuid, node.get_local_node_uuid())

    def test_get_local_node_uuid_two_mismatch(self):
        node_uuids = [uuids.node1, uuids.node2]

        # Write a different uuid to each file
        for id, fn in zip(node_uuids, self.fake_config_files):
            open(os.path.join(
                os.path.dirname(fn),
                node.COMPUTE_ID_FILE), 'w').write(id)

        # Make sure we get an error that identifies the mismatching
        # file with its uuid, as well as what we expected to find
        e = self.assertRaises(exception.InvalidNodeConfiguration,
                              node.get_local_node_uuid)
        expected = ('UUID %s in %s does not match %s' % (
            node_uuids[1],
            os.path.join(os.path.dirname(self.fake_config_files[1]),
                         'compute_id'),
            node_uuids[0]))
        self.assertIn(expected, str(e))
