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
from oslo_utils import timeutils
from oslo_versionedobjects import base as ovo_base
from oslo_versionedobjects import exception as ovo_exc

from nova.compute import manager as compute_manager
from nova import context
from nova import db
from nova import exception
from nova import objects
from nova.objects import aggregate
from nova.objects import fields
from nova.objects import service
from nova import test
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
    'binary': 'nova-fake',
    'topic': 'fake-service-topic',
    'report_count': 1,
    'forced_down': False,
    'disabled': False,
    'disabled_reason': None,
    'last_seen_up': None,
    'version': service.SERVICE_VERSION,
    }

OPTIONAL = ['availability_zone', 'compute_node']


class _TestServiceObject(object):
    def supported_hv_specs_comparator(self, expected, obj_val):
        obj_val = [inst.to_list() for inst in obj_val]
        self.assertJsonEqual(expected, obj_val)

    def pci_device_pools_comparator(self, expected, obj_val):
        obj_val = obj_val.obj_to_primitive()
        self.assertJsonEqual(expected, obj_val)

    def comparators(self):
        return {'stats': self.assertJsonEqual,
                'host_ip': self.assertJsonEqual,
                'supported_hv_specs': self.supported_hv_specs_comparator,
                'pci_device_pools': self.pci_device_pools_comparator}

    def subs(self):
        return {'supported_hv_specs': 'supported_instances',
                'pci_device_pools': 'pci_stats'}

    def _test_query(self, db_method, obj_method, *args, **kwargs):
        self.mox.StubOutWithMock(db, db_method)
        db_exception = kwargs.pop('db_exception', None)
        if db_exception:
            getattr(db, db_method)(self.context, *args, **kwargs).AndRaise(
                db_exception)
        else:
            getattr(db, db_method)(self.context, *args, **kwargs).AndReturn(
                fake_service)
        self.mox.ReplayAll()
        obj = getattr(service.Service, obj_method)(self.context, *args,
                                                   **kwargs)
        if db_exception:
            self.assertIsNone(obj)
        else:
            self.compare_obj(obj, fake_service, allow_missing=OPTIONAL)

    def test_get_by_id(self):
        self._test_query('service_get', 'get_by_id', 123)

    def test_get_by_host_and_topic(self):
        self._test_query('service_get_by_host_and_topic',
                         'get_by_host_and_topic', 'fake-host', 'fake-topic')

    def test_get_by_host_and_binary(self):
        self._test_query('service_get_by_host_and_binary',
                         'get_by_host_and_binary', 'fake-host', 'fake-binary')

    def test_get_by_host_and_binary_raises(self):
        self._test_query('service_get_by_host_and_binary',
                         'get_by_host_and_binary', 'fake-host', 'fake-binary',
                         db_exception=exception.HostBinaryNotFound(
                             host='fake-host', binary='fake-binary'))

    def test_get_by_compute_host(self):
        self._test_query('service_get_by_compute_host', 'get_by_compute_host',
                         'fake-host')

    def test_get_by_args(self):
        self._test_query('service_get_by_host_and_binary', 'get_by_args',
                         'fake-host', 'fake-binary')

    def test_create(self):
        self.mox.StubOutWithMock(db, 'service_create')
        db.service_create(self.context, {'host': 'fake-host',
                                         'version': fake_service['version']}
                          ).AndReturn(fake_service)
        self.mox.ReplayAll()
        service_obj = service.Service(context=self.context)
        service_obj.host = 'fake-host'
        service_obj.create()
        self.assertEqual(fake_service['id'], service_obj.id)
        self.assertEqual(service.SERVICE_VERSION, service_obj.version)

    def test_recreate_fails(self):
        self.mox.StubOutWithMock(db, 'service_create')
        db.service_create(self.context, {'host': 'fake-host',
                                         'version': fake_service['version']}
                          ).AndReturn(fake_service)
        self.mox.ReplayAll()
        service_obj = service.Service(context=self.context)
        service_obj.host = 'fake-host'
        service_obj.create()
        self.assertRaises(exception.ObjectActionError, service_obj.create)

    def test_save(self):
        self.mox.StubOutWithMock(db, 'service_update')
        db.service_update(self.context, 123,
                          {'host': 'fake-host',
                           'version': fake_service['version']}
                          ).AndReturn(fake_service)
        self.mox.ReplayAll()
        service_obj = service.Service(context=self.context)
        service_obj.id = 123
        service_obj.host = 'fake-host'
        service_obj.save()
        self.assertEqual(service.SERVICE_VERSION, service_obj.version)

    @mock.patch.object(db, 'service_create',
                       return_value=fake_service)
    def test_set_id_failure(self, db_mock):
        service_obj = service.Service(context=self.context,
                                      binary='nova-compute')
        service_obj.create()
        self.assertRaises(ovo_exc.ReadOnlyFieldError, setattr,
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

    @mock.patch('nova.db.service_get_all_by_binary')
    def test_get_by_binary(self, mock_get):
        mock_get.return_value = [fake_service]
        services = service.ServiceList.get_by_binary(self.context,
                                                     'fake-binary')
        self.assertEqual(1, len(services))
        mock_get.assert_called_once_with(self.context, 'fake-binary')

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
        fake_compute_node = objects.ComputeNode._from_db_object(
            self.context, objects.ComputeNode(),
            test_compute_node.fake_compute_node)
        self.mox.StubOutWithMock(objects.ComputeNodeList, 'get_all_by_host')
        objects.ComputeNodeList.get_all_by_host(
            self.context, 'fake-host').AndReturn(
                [fake_compute_node])
        self.mox.ReplayAll()
        service_obj = service.Service(id=123, host="fake-host",
                                      binary="nova-compute")
        service_obj._context = self.context
        self.assertEqual(service_obj.compute_node,
                         fake_compute_node)
        # Make sure it doesn't re-fetch this
        service_obj.compute_node

    def test_load_when_orphaned(self):
        service_obj = service.Service()
        service_obj.id = 123
        self.assertRaises(exception.OrphanedObjectError,
                          getattr, service_obj, 'compute_node')

    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host')
    def test_obj_make_compatible_for_compute_node(self, get_all_by_host):
        service_obj = objects.Service(context=self.context)
        fake_service_dict = fake_service.copy()
        fake_compute_obj = objects.ComputeNode(host=fake_service['host'],
                                               service_id=fake_service['id'])
        get_all_by_host.return_value = [fake_compute_obj]

        versions = ovo_base.obj_tree_get_versions('Service')
        versions['ComputeNode'] = '1.10'
        service_obj.obj_make_compatible_from_manifest(fake_service_dict, '1.9',
                                                      versions)
        self.assertEqual(
            fake_compute_obj.obj_to_primitive(target_version='1.10',
                                              version_manifest=versions),
            fake_service_dict['compute_node'])

    @mock.patch('nova.db.service_get_minimum_version')
    def test_get_minimum_version_none(self, mock_get):
        mock_get.return_value = None
        self.assertEqual(0,
                         objects.Service.get_minimum_version(self.context,
                                                             'nova-compute'))
        mock_get.assert_called_once_with(self.context, 'nova-compute')

    @mock.patch('nova.db.service_get_minimum_version')
    def test_get_minimum_version(self, mock_get):
        mock_get.return_value = 123
        self.assertEqual(123,
                         objects.Service.get_minimum_version(self.context,
                                                             'nova-compute'))
        mock_get.assert_called_once_with(self.context, 'nova-compute')

    @mock.patch('nova.db.service_get_minimum_version')
    @mock.patch('nova.objects.service.LOG')
    def test_get_minimum_version_checks_binary(self, mock_log, mock_get):
        mock_get.return_value = None
        self.assertEqual(0,
                         objects.Service.get_minimum_version(self.context,
                                                             'nova-compute'))
        self.assertFalse(mock_log.warning.called)
        self.assertRaises(exception.ObjectActionError,
                         objects.Service.get_minimum_version,
                          self.context,
                          'compute')
        self.assertTrue(mock_log.warning.called)

    @mock.patch('nova.db.service_get_minimum_version')
    def test_get_minimum_version_with_caching(self, mock_get):
        objects.Service.enable_min_version_cache()
        mock_get.return_value = 123
        self.assertEqual(123,
                         objects.Service.get_minimum_version(self.context,
                                                             'nova-compute'))
        self.assertEqual({"nova-compute": 123},
                         objects.Service._MIN_VERSION_CACHE)
        self.assertEqual(123,
                         objects.Service.get_minimum_version(self.context,
                                                             'nova-compute'))
        mock_get.assert_called_once_with(self.context, 'nova-compute')
        objects.Service._SERVICE_VERSION_CACHING = False
        objects.Service.clear_min_version_cache()

    @mock.patch('nova.db.service_get_minimum_version', return_value=2)
    def test_create_above_minimum(self, mock_get):
        with mock.patch('nova.objects.service.SERVICE_VERSION',
                        new=3):
            objects.Service(context=self.context,
                            binary='nova-compute').create()

    @mock.patch('nova.db.service_get_minimum_version', return_value=2)
    def test_create_equal_to_minimum(self, mock_get):
        with mock.patch('nova.objects.service.SERVICE_VERSION',
                        new=2):
            objects.Service(context=self.context,
                            binary='nova-compute').create()

    @mock.patch('nova.db.service_get_minimum_version', return_value=2)
    def test_create_below_minimum(self, mock_get):
        with mock.patch('nova.objects.service.SERVICE_VERSION',
                        new=1):
            self.assertRaises(exception.ServiceTooOld,
                              objects.Service(context=self.context,
                                              binary='nova-compute',
                                              ).create)


class TestServiceObject(test_objects._LocalTest,
                        _TestServiceObject):
    pass


class TestRemoteServiceObject(test_objects._RemoteTest,
                              _TestServiceObject):
    pass


class TestServiceVersion(test.TestCase):
    def setUp(self):
        self.ctxt = context.get_admin_context()
        super(TestServiceVersion, self).setUp()

    def _collect_things(self):
        data = {
            'compute_rpc': compute_manager.ComputeManager.target.version,
        }
        return data

    def test_version(self):
        calculated = self._collect_things()
        self.assertEqual(
            len(service.SERVICE_VERSION_HISTORY), service.SERVICE_VERSION + 1,
            'Service version %i has no history. Please update '
            'nova.objects.service.SERVICE_VERSION_HISTORY '
            'and add %s to it' % (service.SERVICE_VERSION, repr(calculated)))
        current = service.SERVICE_VERSION_HISTORY[service.SERVICE_VERSION]
        self.assertEqual(
            current, calculated,
            'Changes detected that require a SERVICE_VERSION change. Please '
            'increment nova.objects.service.SERVICE_VERSION')

    def test_version_in_init(self):
        self.assertRaises(exception.ObjectActionError,
                          objects.Service,
                          version=123)

    def test_version_set_on_init(self):
        self.assertEqual(service.SERVICE_VERSION,
                         objects.Service().version)

    def test_version_loaded_from_db(self):
        fake_version = fake_service['version'] + 1
        fake_different_service = dict(fake_service)
        fake_different_service['version'] = fake_version
        obj = objects.Service()
        obj._from_db_object(self.ctxt, obj, fake_different_service)
        self.assertEqual(fake_version, obj.version)

    def test_save_noop_with_only_version(self):
        o = objects.Service(context=self.ctxt, id=fake_service['id'])
        o.obj_reset_changes(['id'])
        self.assertEqual(set(['version']), o.obj_what_changed())
        with mock.patch('nova.db.service_update') as mock_update:
            o.save()
            self.assertFalse(mock_update.called)
        o.host = 'foo'
        with mock.patch('nova.db.service_update') as mock_update:
            mock_update.return_value = fake_service
            o.save()
            mock_update.assert_called_once_with(
                self.ctxt, fake_service['id'],
                {'version': service.SERVICE_VERSION,
                 'host': 'foo'})


class TestServiceStatusNotification(test.TestCase):
    def setUp(self):
        self.ctxt = context.get_admin_context()
        super(TestServiceStatusNotification, self).setUp()

    @mock.patch('nova.objects.service.ServiceStatusNotification')
    def _verify_notification(self, service_obj, mock_notification):
        service_obj.save()

        self.assertTrue(mock_notification.called)

        event_type = mock_notification.call_args[1]['event_type']
        priority = mock_notification.call_args[1]['priority']
        publisher = mock_notification.call_args[1]['publisher']
        payload = mock_notification.call_args[1]['payload']

        self.assertEqual(service_obj.host, publisher.host)
        self.assertEqual(service_obj.binary, publisher.binary)
        self.assertEqual(fields.NotificationPriority.INFO, priority)
        self.assertEqual('service', event_type.object)
        self.assertEqual(fields.NotificationAction.UPDATE,
                         event_type.action)
        for field in service.ServiceStatusPayload.SCHEMA:
            if field in fake_service:
                self.assertEqual(fake_service[field], getattr(payload, field))

        mock_notification.return_value.emit.assert_called_once_with(self.ctxt)

    @mock.patch('nova.db.service_update')
    def test_service_update_with_notification(self, mock_db_service_update):
        service_obj = objects.Service(context=self.ctxt, id=fake_service['id'])
        mock_db_service_update.return_value = fake_service
        for key, value in {'disabled': True,
                           'disabled_reason': 'my reason',
                           'forced_down': True}.items():
            setattr(service_obj, key, value)
            self._verify_notification(service_obj)

    @mock.patch('nova.objects.service.ServiceStatusNotification')
    @mock.patch('nova.db.service_update')
    def test_service_update_without_notification(self,
                                                 mock_db_service_update,
                                                 mock_notification):
        service_obj = objects.Service(context=self.ctxt, id=fake_service['id'])
        mock_db_service_update.return_value = fake_service

        for key, value in {'report_count': 13,
                           'last_seen_up': timeutils.utcnow()}.items():
            setattr(service_obj, key, value)
            service_obj.save()
            self.assertFalse(mock_notification.called)
