#    Copyright 2013 IBM Corp.
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

import mock
from oslo_serialization import jsonutils
from oslo_utils import timeutils

from nova import db
from nova import exception
from nova.objects import aggregate
from nova.objects import service
from nova.tests.unit.objects import test_compute_node
from nova.tests.unit.objects import test_objects

NOW = timeutils.utcnow().replace(microsecond=0)
fake_service = {
    'created_at': NOW,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
    'id': 123,
    'host': 'fake-host',
    'binary': 'fake-service',
    'topic': 'fake-service-topic',
    'report_count': 1,
    'disabled': False,
    'disabled_reason': None,
    }

OPTIONAL = ['availability_zone', 'compute_node']


class _TestServiceObject(object):
    def supported_hv_specs_comparator(self, expected, obj_val):
        obj_val = [inst.to_list() for inst in obj_val]
        self.json_comparator(expected, obj_val)

    def pci_device_pools_comparator(self, expected, obj_val):
        obj_val = obj_val.obj_to_primitive()
        self.json_loads_comparator(expected, obj_val)

    def json_loads_comparator(self, expected, obj_val):
        # NOTE(edleafe): This is necessary because the dumps() version of the
        # PciDevicePoolList doesn't maintain ordering, so the output string
        # doesn't always match.
        self.assertEqual(jsonutils.loads(expected), obj_val)

    def comparators(self):
        return {'stats': self.json_comparator,
                'host_ip': self.str_comparator,
                'supported_hv_specs': self.supported_hv_specs_comparator,
                'pci_device_pools': self.pci_device_pools_comparator}

    def subs(self):
        return {'supported_hv_specs': 'supported_instances',
                'pci_device_pools': 'pci_stats'}

    def _test_query(self, db_method, obj_method, *args, **kwargs):
        self.mox.StubOutWithMock(db, db_method)
        getattr(db, db_method)(self.context, *args, **kwargs).AndReturn(
            fake_service)
        self.mox.ReplayAll()
        obj = getattr(service.Service, obj_method)(self.context, *args,
                                                   **kwargs)
        self.compare_obj(obj, fake_service, allow_missing=OPTIONAL)

    def test_get_by_id(self):
        self._test_query('service_get', 'get_by_id', 123)

    def test_get_by_host_and_topic(self):
        self._test_query('service_get_by_host_and_topic',
                         'get_by_host_and_topic', 'fake-host', 'fake-topic')

    def test_get_by_compute_host(self):
        self._test_query('service_get_by_compute_host', 'get_by_compute_host',
                         'fake-host')

    def test_get_by_args(self):
        self._test_query('service_get_by_args', 'get_by_args', 'fake-host',
                         'fake-service')

    def test_with_compute_node(self):
        self.mox.StubOutWithMock(db, 'service_get')
        self.mox.StubOutWithMock(db, 'compute_nodes_get_by_service_id')
        _fake_service = dict(
            fake_service, compute_node=[test_compute_node.fake_compute_node])
        db.service_get(self.context, 123).AndReturn(_fake_service)
        self.mox.ReplayAll()
        service_obj = service.Service.get_by_id(self.context, 123)
        self.assertTrue(service_obj.obj_attr_is_set('compute_node'))
        self.compare_obj(service_obj.compute_node,
                         test_compute_node.fake_compute_node,
                         subs=self.subs(),
                         allow_missing=OPTIONAL,
                         comparators=self.comparators())

    def test_create(self):
        self.mox.StubOutWithMock(db, 'service_create')
        db.service_create(self.context, {'host': 'fake-host'}).AndReturn(
            fake_service)
        self.mox.ReplayAll()
        service_obj = service.Service(context=self.context)
        service_obj.host = 'fake-host'
        service_obj.create()
        self.assertEqual(fake_service['id'], service_obj.id)

    def test_recreate_fails(self):
        self.mox.StubOutWithMock(db, 'service_create')
        db.service_create(self.context, {'host': 'fake-host'}).AndReturn(
            fake_service)
        self.mox.ReplayAll()
        service_obj = service.Service(context=self.context)
        service_obj.host = 'fake-host'
        service_obj.create()
        self.assertRaises(exception.ObjectActionError, service_obj.create,
                          self.context)

    def test_save(self):
        self.mox.StubOutWithMock(db, 'service_update')
        db.service_update(self.context, 123, {'host': 'fake-host'}).AndReturn(
            fake_service)
        self.mox.ReplayAll()
        service_obj = service.Service(context=self.context)
        service_obj.id = 123
        service_obj.host = 'fake-host'
        service_obj.save()

    @mock.patch.object(db, 'service_create',
                       return_value=fake_service)
    def test_set_id_failure(self, db_mock):
        service_obj = service.Service(context=self.context)
        service_obj.create()
        self.assertRaises(exception.ReadOnlyFieldError, setattr,
                          service_obj, 'id', 124)

    def _test_destroy(self):
        self.mox.StubOutWithMock(db, 'service_destroy')
        db.service_destroy(self.context, 123)
        self.mox.ReplayAll()
        service_obj = service.Service(context=self.context)
        service_obj.id = 123
        service_obj.destroy()

    def test_destroy(self):
        # The test harness needs db.service_destroy to work,
        # so avoid leaving it broken here after we're done
        orig_service_destroy = db.service_destroy
        try:
            self._test_destroy()
        finally:
            db.service_destroy = orig_service_destroy

    def test_get_by_topic(self):
        self.mox.StubOutWithMock(db, 'service_get_all_by_topic')
        db.service_get_all_by_topic(self.context, 'fake-topic').AndReturn(
            [fake_service])
        self.mox.ReplayAll()
        services = service.ServiceList.get_by_topic(self.context, 'fake-topic')
        self.assertEqual(1, len(services))
        self.compare_obj(services[0], fake_service, allow_missing=OPTIONAL)

    def test_get_by_host(self):
        self.mox.StubOutWithMock(db, 'service_get_all_by_host')
        db.service_get_all_by_host(self.context, 'fake-host').AndReturn(
            [fake_service])
        self.mox.ReplayAll()
        services = service.ServiceList.get_by_host(self.context, 'fake-host')
        self.assertEqual(1, len(services))
        self.compare_obj(services[0], fake_service, allow_missing=OPTIONAL)

    def test_get_all(self):
        self.mox.StubOutWithMock(db, 'service_get_all')
        db.service_get_all(self.context, disabled=False).AndReturn(
            [fake_service])
        self.mox.ReplayAll()
        services = service.ServiceList.get_all(self.context, disabled=False)
        self.assertEqual(1, len(services))
        self.compare_obj(services[0], fake_service, allow_missing=OPTIONAL)

    def test_get_all_with_az(self):
        self.mox.StubOutWithMock(db, 'service_get_all')
        self.mox.StubOutWithMock(aggregate.AggregateList,
                                 'get_by_metadata_key')
        db.service_get_all(self.context, disabled=None).AndReturn(
            [dict(fake_service, topic='compute')])
        agg = aggregate.Aggregate(context=self.context)
        agg.name = 'foo'
        agg.metadata = {'availability_zone': 'test-az'}
        agg.create()
        agg.hosts = [fake_service['host']]
        aggregate.AggregateList.get_by_metadata_key(self.context,
            'availability_zone', hosts=set(agg.hosts)).AndReturn([agg])
        self.mox.ReplayAll()
        services = service.ServiceList.get_all(self.context, set_zones=True)
        self.assertEqual(1, len(services))
        self.assertEqual('test-az', services[0].availability_zone)

    def test_compute_node(self):
        self.mox.StubOutWithMock(db, 'compute_nodes_get_by_service_id')
        db.compute_nodes_get_by_service_id(self.context, 123).AndReturn(
            [test_compute_node.fake_compute_node])
        self.mox.ReplayAll()
        service_obj = service.Service()
        service_obj._context = self.context
        service_obj.id = 123
        self.compare_obj(service_obj.compute_node,
                         test_compute_node.fake_compute_node,
                         subs=self.subs(),
                         allow_missing=OPTIONAL,
                         comparators=self.comparators())
        # Make sure it doesn't re-fetch this
        service_obj.compute_node

    def test_load_when_orphaned(self):
        service_obj = service.Service()
        service_obj.id = 123
        self.assertRaises(exception.OrphanedObjectError,
                          getattr, service_obj, 'compute_node')


class TestServiceObject(test_objects._LocalTest,
                        _TestServiceObject):
    pass


class TestRemoteServiceObject(test_objects._RemoteTest,
                              _TestServiceObject):
    pass
