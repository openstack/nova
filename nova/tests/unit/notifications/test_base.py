# Copyright (c) 2017 OpenStack Foundation
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
import datetime

from keystoneauth1 import exceptions as ks_exc
import mock

from nova import context as nova_context
from nova.notifications import base
from nova import test
from nova.tests.unit import fake_instance
from nova.tests import uuidsentinel as uuids
from nova import utils


class TestNullSafeUtils(test.NoDBTestCase):
    def test_null_safe_isotime(self):
        dt = None
        self.assertEqual('', base.null_safe_isotime(dt))
        dt = datetime.datetime(second=1,
                              minute=1,
                              hour=1,
                              day=1,
                              month=1,
                              year=2017)
        self.assertEqual(utils.strtime(dt), base.null_safe_isotime(dt))

    def test_null_safe_str(self):
        line = None
        self.assertEqual('', base.null_safe_str(line))
        line = 'test'
        self.assertEqual(line, base.null_safe_str(line))


class TestSendInstanceUpdateNotification(test.NoDBTestCase):

    @mock.patch('nova.notifications.objects.base.NotificationBase.emit',
                new_callable=mock.NonCallableMock)  # asserts not called
    # TODO(mriedem): Rather than mock is_enabled, it would be better to
    # configure oslo_messaging_notifications.driver=['noop']
    @mock.patch('nova.rpc.NOTIFIER.is_enabled', return_value=False)
    def test_send_versioned_instance_update_notification_disabled(self,
                                                                  mock_enabled,
                                                                  mock_info):
        """Tests the case that versioned notifications are disabled which makes
        _send_versioned_instance_update_notification a noop.
        """
        base._send_versioned_instance_update(mock.sentinel.ctxt,
                                             mock.sentinel.instance,
                                             mock.sentinel.payload,
                                             mock.sentinel.host,
                                             mock.sentinel.service)

    @mock.patch.object(base, 'bandwidth_usage')
    @mock.patch.object(base, '_compute_states_payload')
    @mock.patch('nova.rpc.get_notifier')
    @mock.patch.object(base, 'info_from_instance')
    def test_send_legacy_instance_update_notification(self, mock_info,
                                                      mock_get_notifier,
                                                      mock_states,
                                                      mock_bw):
        """Tests the case that versioned notifications are disabled and
        assert that this does not prevent sending the unversioned
        instance.update notification.
        """

        self.flags(notification_format='unversioned', group='notifications')
        base.send_instance_update_notification(mock.sentinel.ctxt,
                                               mock.sentinel.instance)

        mock_get_notifier.return_value.info.assert_called_once_with(
            mock.sentinel.ctxt, 'compute.instance.update', mock.ANY)
        mock_info.assert_called_once_with(
            mock.sentinel.ctxt, mock.sentinel.instance, None,
            populate_image_ref_url=True)

    @mock.patch('nova.image.api.API.generate_image_url',
                side_effect=ks_exc.EndpointNotFound)
    def test_info_from_instance_image_api_endpoint_not_found_no_token(
            self, mock_gen_image_url):
        """Tests the case that we fail to generate the image ref url because
        CONF.glance.api_servers isn't set and we have a context without an
        auth token, like in the case of a periodic task using an admin context.
        In this case, we expect the payload field 'image_ref_url' to just be
        the instance.image_ref (image ID for a non-volume-backed server).
        """
        ctxt = nova_context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctxt, image_ref=uuids.image)
        instance.system_metadata = {}
        instance.metadata = {}
        payload = base.info_from_instance(ctxt, instance, network_info=None,
                                          populate_image_ref_url=True)
        self.assertEqual(instance.image_ref, payload['image_ref_url'])
        mock_gen_image_url.assert_called_once_with(instance.image_ref, ctxt)

    @mock.patch('nova.image.api.API.generate_image_url',
                side_effect=ks_exc.EndpointNotFound)
    def test_info_from_instance_image_api_endpoint_not_found_with_token(
            self, mock_gen_image_url):
        """Tests the case that we fail to generate the image ref url because
        an EndpointNotFound error is raised up from the image API but the
        context does have a token so we pass the error through.
        """
        ctxt = nova_context.RequestContext(
            'fake-user', 'fake-project', auth_token='fake-token')
        instance = fake_instance.fake_instance_obj(ctxt, image_ref=uuids.image)
        self.assertRaises(ks_exc.EndpointNotFound, base.info_from_instance,
                          ctxt, instance, network_info=None,
                          populate_image_ref_url=True)
        mock_gen_image_url.assert_called_once_with(instance.image_ref, ctxt)

    @mock.patch('nova.image.api.API.generate_image_url')
    def test_info_from_instance_not_call_generate_image_url(
            self, mock_gen_image_url):
        ctxt = nova_context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctxt, image_ref=uuids.image)
        instance.system_metadata = {}
        instance.metadata = {}
        base.info_from_instance(ctxt, instance, network_info=None,
                                populate_image_ref_url=False)

        mock_gen_image_url.assert_not_called()


class TestBandwidthUsage(test.NoDBTestCase):
    @mock.patch('nova.context.RequestContext.elevated')
    @mock.patch('nova.network.API')
    @mock.patch('nova.objects.BandwidthUsageList.get_by_uuids')
    def test_context_elevated(self, mock_get_bw_usage, mock_nw_api,
                              mock_elevated):
        context = nova_context.RequestContext('fake', 'fake')
        # We need this to not be a NovaObject so the old school
        # get_instance_nw_info will run.
        instance = {'uuid': uuids.instance}
        audit_start = 'fake'

        base.bandwidth_usage(context, instance, audit_start)

        network_api = mock_nw_api.return_value
        network_api.get_instance_nw_info.assert_called_once_with(
            mock_elevated.return_value, instance)
        mock_get_bw_usage.assert_called_once_with(
            mock_elevated.return_value, [uuids.instance], audit_start)
        mock_elevated.assert_called_once_with(read_deleted='yes')
