# Copyright 2013 Netease Corporation
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
Tests for availability zones
"""

import mock
import six

from nova import availability_zones as az
import nova.conf
from nova import context
from nova.db import api as db
from nova import objects
from nova import test
from nova.tests import uuidsentinel

CONF = nova.conf.CONF


class AvailabilityZoneTestCases(test.TestCase):
    """Test case for aggregate based availability zone."""

    def setUp(self):
        super(AvailabilityZoneTestCases, self).setUp()
        self.host = 'me'
        self.availability_zone = 'nova-test'
        self.default_az = CONF.default_availability_zone
        self.default_in_az = CONF.internal_service_availability_zone
        self.context = context.get_admin_context()
        self.agg = self._create_az('az_agg', self.availability_zone)

    def tearDown(self):
        self.agg.destroy()
        super(AvailabilityZoneTestCases, self).tearDown()

    def _create_az(self, agg_name, az_name):
        agg_meta = {'name': agg_name, 'uuid': uuidsentinel.agg_uuid,
                    'metadata': {'availability_zone': az_name}}
        agg = objects.Aggregate(self.context, **agg_meta)
        agg.create()
        agg = objects.Aggregate.get_by_id(self.context, agg.id)
        return agg

    def _update_az(self, aggregate, az_name):
        aggregate.update_metadata({'availability_zone': az_name})

    def _create_service_with_topic(self, topic, host, disabled=False):
        values = {
            'binary': 'nova-bin',
            'host': host,
            'topic': topic,
            'disabled': disabled,
        }
        return db.service_create(self.context, values)

    def _destroy_service(self, service):
        return db.service_destroy(self.context, service['id'])

    def _add_to_aggregate(self, service, aggregate):
        aggregate.add_host(service['host'])

    def _delete_from_aggregate(self, service, aggregate):
        aggregate.delete_host(service['host'])

    def test_rest_availability_zone_reset_cache(self):
        az._get_cache().add('cache', 'fake_value')
        az.reset_cache()
        self.assertIsNone(az._get_cache().get('cache'))

    def test_update_host_availability_zone_cache(self):
        """Test availability zone cache could be update."""
        service = self._create_service_with_topic('compute', self.host)

        # Create a new aggregate with an AZ and add the host to the AZ
        az_name = 'az1'
        cache_key = az._make_cache_key(self.host)
        agg_az1 = self._create_az('agg-az1', az_name)
        self._add_to_aggregate(service, agg_az1)
        az.update_host_availability_zone_cache(self.context, self.host)
        self.assertEqual('az1', az._get_cache().get(cache_key))
        az.update_host_availability_zone_cache(self.context, self.host, 'az2')
        self.assertEqual('az2', az._get_cache().get(cache_key))

    def test_set_availability_zone_compute_service(self):
        """Test for compute service get right availability zone."""
        service = self._create_service_with_topic('compute', self.host)
        services = db.service_get_all(self.context)

        # The service is not add into aggregate, so confirm it is default
        # availability zone.
        new_service = az.set_availability_zones(self.context, services)[0]
        self.assertEqual(self.default_az, new_service['availability_zone'])

        # The service is added into aggregate, confirm return the aggregate
        # availability zone.
        self._add_to_aggregate(service, self.agg)
        new_service = az.set_availability_zones(self.context, services)[0]
        self.assertEqual(self.availability_zone,
                         new_service['availability_zone'])

        self._destroy_service(service)

    def test_set_availability_zone_unicode_key(self):
        """Test set availability zone cache key is unicode."""
        service = self._create_service_with_topic('network', self.host)
        services = db.service_get_all(self.context)
        az.set_availability_zones(self.context, services)
        self.assertIsInstance(services[0]['host'], six.text_type)
        cached_key = az._make_cache_key(services[0]['host'])
        self.assertIsInstance(cached_key, str)
        self._destroy_service(service)

    def test_set_availability_zone_not_compute_service(self):
        """Test not compute service get right availability zone."""
        service = self._create_service_with_topic('network', self.host)
        services = db.service_get_all(self.context)
        new_service = az.set_availability_zones(self.context, services)[0]
        self.assertEqual(self.default_in_az, new_service['availability_zone'])
        self._destroy_service(service)

    def test_get_host_availability_zone(self):
        """Test get right availability zone by given host."""
        self.assertEqual(self.default_az,
                        az.get_host_availability_zone(self.context, self.host))

        service = self._create_service_with_topic('compute', self.host)
        self._add_to_aggregate(service, self.agg)

        self.assertEqual(self.availability_zone,
                        az.get_host_availability_zone(self.context, self.host))

    def test_update_host_availability_zone(self):
        """Test availability zone could be update by given host."""
        service = self._create_service_with_topic('compute', self.host)

        # Create a new aggregate with an AZ and add the host to the AZ
        az_name = 'az1'
        agg_az1 = self._create_az('agg-az1', az_name)
        self._add_to_aggregate(service, agg_az1)
        self.assertEqual(az_name,
                    az.get_host_availability_zone(self.context, self.host))
        # Update AZ
        new_az_name = 'az2'
        self._update_az(agg_az1, new_az_name)
        self.assertEqual(new_az_name,
                    az.get_host_availability_zone(self.context, self.host))

    def test_delete_host_availability_zone(self):
        """Test availability zone could be deleted successfully."""
        service = self._create_service_with_topic('compute', self.host)

        # Create a new aggregate with an AZ and add the host to the AZ
        az_name = 'az1'
        agg_az1 = self._create_az('agg-az1', az_name)
        self._add_to_aggregate(service, agg_az1)
        self.assertEqual(az_name,
                    az.get_host_availability_zone(self.context, self.host))
        # Delete the AZ via deleting the aggregate
        self._delete_from_aggregate(service, agg_az1)
        self.assertEqual(self.default_az,
                    az.get_host_availability_zone(self.context, self.host))

    def test_get_availability_zones(self):
        """Test get_availability_zones."""

        # When the param get_only_available of get_availability_zones is set
        # to default False, it returns two lists, zones with at least one
        # enabled services, and zones with no enabled services,
        # when get_only_available is set to True, only return a list of zones
        # with at least one enabled services.
        # Use the following test data:
        #
        # zone         host        enabled
        # nova-test    host1       Yes
        # nova-test    host2       No
        # nova-test2   host3       Yes
        # nova-test3   host4       No
        # <default>    host5       No

        agg2 = self._create_az('agg-az2', 'nova-test2')
        agg3 = self._create_az('agg-az3', 'nova-test3')

        service1 = self._create_service_with_topic('compute', 'host1',
                                                   disabled=False)
        service2 = self._create_service_with_topic('compute', 'host2',
                                                   disabled=True)
        service3 = self._create_service_with_topic('compute', 'host3',
                                                   disabled=False)
        service4 = self._create_service_with_topic('compute', 'host4',
                                                   disabled=True)
        self._create_service_with_topic('compute', 'host5',
                                        disabled=True)

        self._add_to_aggregate(service1, self.agg)
        self._add_to_aggregate(service2, self.agg)
        self._add_to_aggregate(service3, agg2)
        self._add_to_aggregate(service4, agg3)

        zones, not_zones = az.get_availability_zones(self.context)

        self.assertEqual(['nova-test', 'nova-test2'], zones)
        self.assertEqual(['nova-test3', 'nova'], not_zones)

        zones = az.get_availability_zones(self.context, True)

        self.assertEqual(['nova-test', 'nova-test2'], zones)

        zones, not_zones = az.get_availability_zones(self.context,
                                                     with_hosts=True)

        self.assertJsonEqual(zones,
                         [(u'nova-test2', set([u'host3'])),
                                 (u'nova-test', set([u'host1']))])
        self.assertJsonEqual(not_zones,
                         [(u'nova-test3', set([u'host4'])),
                                 (u'nova', set([u'host5']))])

    def test_get_instance_availability_zone_default_value(self):
        """Test get right availability zone by given an instance."""
        fake_inst = objects.Instance(host=self.host,
                                     availability_zone=None)

        self.assertEqual(self.default_az,
                az.get_instance_availability_zone(self.context, fake_inst))

    def test_get_instance_availability_zone_from_aggregate(self):
        """Test get availability zone from aggregate by given an instance."""
        host = 'host170'
        service = self._create_service_with_topic('compute', host)
        self._add_to_aggregate(service, self.agg)

        fake_inst = objects.Instance(host=host,
                                     availability_zone=self.availability_zone)

        self.assertEqual(self.availability_zone,
                az.get_instance_availability_zone(self.context, fake_inst))

    @mock.patch.object(az._get_cache(), 'get')
    def test_get_instance_availability_zone_cache_differs(self, cache_get):
        host = 'host170'
        service = self._create_service_with_topic('compute', host)
        self._add_to_aggregate(service, self.agg)
        cache_get.return_value = self.default_az

        fake_inst = objects.Instance(host=host,
                                     availability_zone=self.availability_zone)
        self.assertEqual(
            self.availability_zone,
            az.get_instance_availability_zone(self.context, fake_inst))

    def test_get_instance_availability_zone_no_host(self):
        """Test get availability zone from instance if host is None."""
        fake_inst = objects.Instance(host=None, availability_zone='inst-az')

        result = az.get_instance_availability_zone(self.context, fake_inst)
        self.assertEqual('inst-az', result)

    def test_get_instance_availability_zone_no_host_set(self):
        """Test get availability zone from instance if host not set.

        This is testing the case in the compute API where the Instance object
        does not have the host attribute set because it's just the object that
        goes into the BuildRequest, it wasn't actually pulled from the DB. The
        instance in this case doesn't actually get inserted into the DB until
        it reaches conductor. So the host attribute may not be set but we
        expect availability_zone always will in the API because of
        _validate_and_build_base_options setting a default value which goes
        into the object.
        """
        fake_inst = objects.Instance(availability_zone='inst-az')
        result = az.get_instance_availability_zone(self.context, fake_inst)
        self.assertEqual('inst-az', result)

    def test_get_instance_availability_zone_no_host_no_az(self):
        """Test get availability zone if neither host nor az is set."""
        fake_inst = objects.Instance(host=None, availability_zone=None)

        result = az.get_instance_availability_zone(self.context, fake_inst)
        self.assertIsNone(result)
