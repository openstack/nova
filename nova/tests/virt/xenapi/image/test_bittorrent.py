# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
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

import pkg_resources

import mox

from nova import context
from nova.openstack.common.gettextutils import _
from nova import test
from nova.tests.virt.xenapi import stubs
from nova.virt.xenapi import driver as xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi.image import bittorrent
from nova.virt.xenapi import vm_utils


class TestBittorrentStore(stubs.XenAPITestBase):
    def setUp(self):
        super(TestBittorrentStore, self).setUp()
        self.store = bittorrent.BittorrentStore()
        self.mox = mox.Mox()

        self.flags(xenapi_torrent_base_url='http://foo',
                   xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass')

        self.context = context.RequestContext(
                'user', 'project', auth_token='foobar')

        fake.reset()
        stubs.stubout_session(self.stubs, fake.SessionBase)

        def mock_iter_eps(namespace):
            return []

        self.stubs.Set(pkg_resources, 'iter_entry_points', mock_iter_eps)

        driver = xenapi_conn.XenAPIDriver(False)
        self.session = driver._session

        self.stubs.Set(
                vm_utils, 'get_sr_path', lambda *a, **kw: '/fake/sr/path')

        self.instance = {'uuid': 'blah',
                         'system_metadata': {'image_xenapi_use_agent': 'true'},
                         'auto_disk_config': True,
                         'os_type': 'default',
                         'xenapi_use_agent': 'true'}

    def test_download_image(self):

        params = {'image_id': 'fake_image_uuid',
                  'sr_path': '/fake/sr/path',
                  'torrent_download_stall_cutoff': 600,
                  'torrent_listen_port_end': 6891,
                  'torrent_listen_port_start': 6881,
                  'torrent_max_last_accessed': 86400,
                  'torrent_max_seeder_processes_per_host': 1,
                  'torrent_seed_chance': 1.0,
                  'torrent_seed_duration': 3600,
                  'torrent_url': 'http://foo/fake_image_uuid.torrent',
                  'uuid_stack': ['uuid1']}

        self.stubs.Set(vm_utils, '_make_uuid_stack',
                       lambda *a, **kw: ['uuid1'])

        self.mox.StubOutWithMock(self.session, 'call_plugin_serialized')
        self.session.call_plugin_serialized(
                'bittorrent', 'download_vhd', **params)
        self.mox.ReplayAll()

        vdis = self.store.download_image(
                self.context, self.session, self.instance, 'fake_image_uuid')

        self.mox.VerifyAll()

    def test_upload_image(self):
        self.assertRaises(NotImplementedError, self.store.upload_image,
                self.context, self.session, self.instance, ['fake_vdi_uuid'],
                'fake_image_uuid')


def bad_fetcher(instance, image_id):
    raise test.TestingException("just plain bad.")


def another_fetcher(instance, image_id):
    return "http://www.foobar.com/%s" % image_id


class MockEntryPoint(object):
    name = "torrent_url"

    def load(self):
        return another_fetcher


class LookupTorrentURLTestCase(test.NoDBTestCase):
    def setUp(self):
        super(LookupTorrentURLTestCase, self).setUp()
        self.store = bittorrent.BittorrentStore()
        self.instance = {'uuid': 'fakeuuid'}
        self.image_id = 'fakeimageid'

    def _mock_iter_none(self, namespace):
        return []

    def test_default_fetch_url_no_base_url_set(self):
        self.flags(xenapi_torrent_base_url=None)
        self.stubs.Set(pkg_resources, 'iter_entry_points',
                       self._mock_iter_none)

        exc = self.assertRaises(
                RuntimeError, self.store._lookup_torrent_url_fn)
        self.assertEqual(_('Cannot create default bittorrent URL without'
                           ' xenapi_torrent_base_url set'),
                         str(exc))

    def test_default_fetch_url_base_url_is_set(self):
        self.flags(xenapi_torrent_base_url='http://foo')
        self.stubs.Set(pkg_resources, 'iter_entry_points',
                       self._mock_iter_none)

        lookup_fn = self.store._lookup_torrent_url_fn()
        self.assertEqual('http://foo/fakeimageid.torrent',
                         lookup_fn(self.instance, self.image_id))

    def test_with_extension(self):
        def mock_iter_single(namespace):
            return [MockEntryPoint()]

        self.stubs.Set(pkg_resources, 'iter_entry_points', mock_iter_single)

        lookup_fn = self.store._lookup_torrent_url_fn()
        self.assertEqual("http://www.foobar.com/%s" % self.image_id,
                         lookup_fn(self.instance, self.image_id))

    def test_multiple_extensions_found(self):
        def mock_iter_multiple(namespace):
            return [MockEntryPoint(), MockEntryPoint()]

        self.stubs.Set(pkg_resources, 'iter_entry_points', mock_iter_multiple)

        exc = self.assertRaises(
                RuntimeError, self.store._lookup_torrent_url_fn)
        self.assertEqual(_('Multiple torrent URL fetcher extension found.'
                           ' Failing.'),
                         str(exc))
