# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (c) 2010 Citrix Systems, Inc.
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

"""Test suite for Xen Storage Manager Volume Driver."""

import os

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova.openstack.common import log as logging
from nova import test
from nova.tests.xenapi import stubs
from nova.virt.xenapi import driver as xenapi_conn
from nova.virt.xenapi import fake as xenapi_fake
from nova.virt.xenapi import volume_utils
from nova.volume import xensm

LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS


class XenSMTestCase(stubs.XenAPITestBase):
    """Unit tests for Xen Storage Manager Volume operations."""

    def _get_sm_backend_params(self):
        config_params = ("name_label=testsmbackend "
                         "server=localhost "
                         "serverpath=/tmp/nfspath")
        params = dict(flavor_id=1,
                      sr_uuid=None,
                      sr_type='nfs',
                      config_params=config_params)
        return params

    def setUp(self):
        super(XenSMTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.flags(connection_type='xenapi',
                   xenapi_connection_url='http://test_url',
                   xenapi_connection_username='test_user',
                   xenapi_connection_password='test_pass')
        stubs.stubout_session(self.stubs, xenapi_fake.SessionBase)
        xenapi_fake.reset()
        self.driver = xensm.XenSMDriver()
        self.driver.db = db

    def _setup_step(self, ctxt):
        # Create a fake backend conf
        params = self._get_sm_backend_params()
        beconf = db.sm_backend_conf_create(ctxt,
                                           params)
        # Call setup, the one time operation that will create a backend SR
        self.driver.do_setup(ctxt)
        return beconf

    def test_do_setup(self):
        ctxt = context.get_admin_context()
        beconf = self._setup_step(ctxt)
        beconf = db.sm_backend_conf_get(ctxt, beconf['id'])
        self.assertIsInstance(beconf['sr_uuid'], basestring)

    def _create_volume(self, size=0):
        """Create a volume object."""
        vol = {}
        vol['size'] = size
        vol['user_id'] = 'fake'
        vol['project_id'] = 'fake'
        vol['host'] = 'localhost'
        vol['availability_zone'] = FLAGS.storage_availability_zone
        vol['status'] = "creating"
        vol['attach_status'] = "detached"
        return db.volume_create(self.context, vol)

    def test_create_volume(self):
        ctxt = context.get_admin_context()
        beconf = self._setup_step(ctxt)
        volume = self._create_volume()
        self.assertNotRaises(None, self.driver.create_volume, volume)
        self.assertNotRaises(None,
                             db.sm_volume_get,
                             ctxt,
                             volume['id'])

    def test_local_path(self):
        ctxt = context.get_admin_context()
        volume = self._create_volume()
        val = self.driver.local_path(volume)
        self.assertIsInstance(val, basestring)

    def test_delete_volume(self):
        ctxt = context.get_admin_context()
        beconf = self._setup_step(ctxt)
        volume = self._create_volume()
        self.driver.create_volume(volume)
        self.assertNotRaises(None, self.driver.delete_volume, volume)
        self.assertRaises(exception.NotFound,
                          db.sm_volume_get,
                          ctxt,
                          volume['id'])

    def test_delete_volume_raises_notfound(self):
        ctxt = context.get_admin_context()
        beconf = self._setup_step(ctxt)
        self.assertRaises(exception.NotFound,
                          self.driver.delete_volume,
                          {'id': "FA15E-1D"})

    def _get_expected_conn(self, beconf, vol):
        expected = {}
        expected['volume_id'] = unicode(vol['id'])
        expected['flavor_id'] = beconf['flavor_id']
        expected['sr_uuid'] = unicode(beconf['sr_uuid'])
        expected['sr_type'] = unicode(beconf['sr_type'])
        return expected

    def test_initialize_connection(self):
        ctxt = context.get_admin_context()
        beconf = self._setup_step(ctxt)
        beconf = db.sm_backend_conf_get(ctxt, beconf['id'])
        volume = self._create_volume()
        self.driver.create_volume(volume)
        expected = self._get_expected_conn(beconf, volume)
        conn = self.driver.initialize_connection(volume, 'fakeConnector')
        res = {}
        for key in ['volume_id', 'flavor_id', 'sr_uuid', 'sr_type']:
            res[key] = conn['data'][key]
        self.assertDictMatch(expected, res)
        self.assertEqual(set(conn['data']['introduce_sr_keys']),
                         set([u'sr_type', u'server', u'serverpath']))
