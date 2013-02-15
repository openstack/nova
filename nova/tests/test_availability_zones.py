# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from oslo.config import cfg

from nova import availability_zones as az
from nova import context
from nova import db
from nova import test

CONF = cfg.CONF
CONF.import_opt('internal_service_availability_zone',
                'nova.availability_zones')
CONF.import_opt('default_availability_zone',
                'nova.availability_zones')


class AvailabilityZoneTestCases(test.TestCase):
    """Test case for aggregate based availability zone."""

    def setUp(self):
        super(AvailabilityZoneTestCases, self).setUp()
        self.host = 'me'
        self.availability_zone = 'nova-test'
        self.default_az = CONF.default_availability_zone
        self.default_in_az = CONF.internal_service_availability_zone
        self.context = context.get_admin_context()

        agg = {'name': 'agg1'}
        self.agg = db.aggregate_create(self.context, agg)

        metadata = {'availability_zone': self.availability_zone}
        db.aggregate_metadata_add(self.context, self.agg['id'], metadata)

    def tearDown(self):
        db.aggregate_delete(self.context, self.agg['id'])
        super(AvailabilityZoneTestCases, self).tearDown()

    def _create_service_with_topic(self, topic):
        values = {
            'binary': 'bin',
            'host': self.host,
            'topic': topic,
        }
        return db.service_create(self.context, values)

    def _destroy_service(self, service):
        return db.service_destroy(self.context, service['id'])

    def _add_to_aggregate(self, service):
        return db.aggregate_host_add(self.context,
                                     self.agg['id'], service['host'])

    def _delete_from_aggregate(self, service):
        return db.aggregate_host_delete(self.context,
                                        self.agg['id'], service['host'])

    def test_set_availability_zone_compute_service(self):
        """Test for compute service get right availability zone."""
        service = self._create_service_with_topic('compute')
        services = db.service_get_all(self.context)

        # The service is not add into aggregate, so confirm it is default
        # availability zone.
        new_service = az.set_availability_zones(self.context, services)[0]
        self.assertEquals(new_service['availability_zone'],
                          self.default_az)

        # The service is added into aggregate, confirm return the aggregate
        # availability zone.
        self._add_to_aggregate(service)
        new_service = az.set_availability_zones(self.context, services)[0]
        self.assertEquals(new_service['availability_zone'],
                          self.availability_zone)

        self._destroy_service(service)

    def test_set_availability_zone_not_compute_service(self):
        """Test not compute service get right availability zone."""
        service = self._create_service_with_topic('network')
        services = db.service_get_all(self.context)
        new_service = az.set_availability_zones(self.context, services)[0]
        self.assertEquals(new_service['availability_zone'],
                          self.default_in_az)
        self._destroy_service(service)

    def test_get_host_availability_zone(self):
        """Test get right availability zone by given host."""
        self.assertEquals(self.default_az,
                        az.get_host_availability_zone(self.context, self.host))

        service = self._create_service_with_topic('compute')
        self._add_to_aggregate(service)

        self.assertEquals(self.availability_zone,
                        az.get_host_availability_zone(self.context, self.host))
