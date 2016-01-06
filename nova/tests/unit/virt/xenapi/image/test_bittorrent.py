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

from mox3 import mox
import six

from nova import context
from nova import test
from nova.tests.unit.virt.xenapi import stubs
from nova.virt.xenapi import driver as xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi.image import bittorrent
from nova.virt.xenapi import vm_utils


class TestBittorrentStore(stubs.XenAPITestBaseNoDB):
    def setUp(self):
        super(TestBittorrentStore, self).setUp()
        self.store = bittorrent.BittorrentStore()
        self.mox = mox.Mox()

        self.flags(torrent_base_url='http://foo',
                   connection_url='test_url',
                   connection_password='test_pass',
                   group='xenserver')

        self.context = context.RequestContext(
                'user', 'project', auth_token='foobar')

        fake.reset()
        stubs.stubout_session(self.stubs, fake.SessionBase)

        driver = xenapi_conn.XenAPIDriver(False)
        self.session = driver._session

        self.stubs.Set(
                vm_utils, 'get_sr_path', lambda *a, **kw: '/fake/sr/path')

    def test_download_image(self):

        instance = {'uuid': '00000000-0000-0000-0000-000000007357'}
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

        self.store.download_image(self.context, self.session,
                                  instance, 'fake_image_uuid')

        self.mox.VerifyAll()

    def test_upload_image(self):
        self.assertRaises(NotImplementedError, self.store.upload_image,
                self.context, self.session, mox.IgnoreArg, 'fake_image_uuid',
                ['fake_vdi_uuid'])


class LookupTorrentURLTestCase(test.NoDBTestCase):
    def setUp(self):
        super(LookupTorrentURLTestCase, self).setUp()
        self.store = bittorrent.BittorrentStore()
        self.image_id = 'fakeimageid'

    def test_default_fetch_url_no_base_url_set(self):
        self.flags(torrent_base_url=None,
                   group='xenserver')

        exc = self.assertRaises(
                RuntimeError, self.store._lookup_torrent_url_fn)
        self.assertEqual('Cannot create default bittorrent URL without'
                         ' xenserver.torrent_base_url configuration option'
                         ' set.',
                         six.text_type(exc))

    def test_default_fetch_url_base_url_is_set(self):
        self.flags(torrent_base_url='http://foo',
                   group='xenserver')

        lookup_fn = self.store._lookup_torrent_url_fn()
        self.assertEqual('http://foo/fakeimageid.torrent',
                         lookup_fn(self.image_id))

    def test_invalid_base_url_warning_logged(self):
        self.flags(torrent_base_url='www.foo.com',
                   group='xenserver')

        # Make sure a warning is logged when an invalid base URL is set,
        # where invalid means it does not contain any slash characters
        warnings = []

        def fake_warn(msg):
            warnings.append(msg)

        self.stubs.Set(bittorrent.LOG, 'warning', fake_warn)

        lookup_fn = self.store._lookup_torrent_url_fn()
        self.assertEqual('fakeimageid.torrent',
                         lookup_fn(self.image_id))

        self.assertTrue(any('does not contain a slash character' in msg for
                            msg in warnings),
                        '_lookup_torrent_url_fn() did not log a warning '
                        'message when the torrent_base_url did not contain a '
                        'slash character.')
