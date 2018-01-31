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
import six

from nova.compute import manager as compute_manager
from nova import context
from nova import db
from nova import exception
from nova import objects
from nova.objects import aggregate
from nova.objects import service
from nova import test
from nova.tests import fixtures
from nova.tests.unit.objects import test_compute_node
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel

NOW = timeutils.utcnow().replace(microsecond=0)


def _fake_service(**kwargs):
    fake_service = {
        'created_at': NOW,
        'updated_at': None,
        'deleted_at': None,
        'deleted': False,
        'id': 123,
        'uuid': uuidsentinel.service,
        'host': 'fake-host',
        'binary': 'nova-compute',
        'topic': 'fake-service-topic',
        'report_count': 1,
        'forced_down': False,
        'disabled': False,
        'disabled_reason': None,
        'last_seen_up': None,
        'version': service.SERVICE_VERSION,
        }
    fake_service.update(kwargs)
    return fake_service

fake_service = _fake_service()

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
        db_exception = kwargs.pop('db_exception', None)
        if db_exception:
            with mock.patch.object(db, db_method, side_effect=db_exception) \
                    as mock_db_method:
                obj = getattr(service.Service, obj_method)(self.context, *args,
                                                           **kwargs)
                self.assertIsNone(obj)
                mock_db_method.assert_called_once_with(self.context, *args,
                                                       **kwargs)
        else:
            with mock.patch.object(db, db_method, return_value=fake_service) \
                    as mock_db_method:
                obj = getattr(service.Service, obj_method)(self.context, *args,
                                                           **kwargs)
                self.compare_obj(obj, fake_service, allow_missing=OPTIONAL)
                mock_db_method.assert_called_once_with(self.context, *args,
                                                       **kwargs)

    def test_get_by_id(self):
        self._test_query('service_get', 'get_by_id', 123)

    def test_get_by_uuid(self):
        self._test_query('service_get_by_uuid', 'get_by_uuid',
                         uuidsentinel.service_uuid)

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

    @mock.patch.object(db, 'service_create', return_value=fake_service)
    def test_create(self, mock_service_create):
        service_obj = service.Service(context=self.context)
        service_obj.host = 'fake-host'
        service_obj.uuid = uuidsentinel.service2
        service_obj.create()
        self.assertEqual(fake_service['id'], service_obj.id)
        self.assertEqual(service.SERVICE_VERSION, service_obj.version)
        mock_service_create.assert_called_once_with(
                       self.context, {'host': 'fake-host',
                                      'uuid': uuidsentinel.service2,
                                      'version': fake_service['version']})

    @mock.patch('nova.objects.service.uuidutils.generate_uuid',
                return_value=uuidsentinel.service3)
    @mock.patch.object(db, 'service_create', return_value=fake_service)
    def test_create_without_uuid_generates_one(
            self, mock_service_create, generate_uuid):
        service_obj = service.Service(context=self.context)
        service_obj.create()
        create_args = mock_service_create.call_args[0][1]
        self.assertEqual(generate_uuid.return_value, create_args['uuid'])

    @mock.patch.object(db, 'service_create', return_value=fake_service)
    def test_recreate_fails(self, mock_service_create):
        service_obj = service.Service(context=self.context)
        service_obj.host = 'fake-host'
        service_obj.create()
        self.assertRaises(exception.ObjectActionError, service_obj.create)
        mock_service_create(self.context, {'host': 'fake-host',
                                         'version': fake_service['version']})

    @mock.patch('nova.objects.Service._send_notification')
    @mock.patch.object(db, 'service_update', return_value=fake_service)
    def test_save(self, mock_service_update, mock_notify):
        service_obj = service.Service(context=self.context)
        service_obj.id = 123
        service_obj.host = 'fake-host'
        service_obj.save()
        self.assertEqual(service.SERVICE_VERSION, service_obj.version)
        mock_service_update.assert_called_once_with(
            self.context, 123, {'host': 'fake-host',
                                'version': fake_service['version']})

    @mock.patch.object(db, 'service_create',
                       return_value=fake_service)
    def test_set_id_failure(self, db_mock):
        service_obj = service.Service(context=self.context,
                                      binary='nova-compute')
        service_obj.create()
        self.assertRaises(ovo_exc.ReadOnlyFieldError, setattr,
                          service_obj, 'id', 124)

    @mock.patch('nova.objects.Service._send_notification')
    @mock.patch.object(db, 'service_destroy')
    def _test_destroy(self, mock_service_destroy, mock_notify):
        service_obj = service.Service(context=self.context)
        service_obj.id = 123
        service_obj.destroy()
        mock_service_destroy.assert_called_once_with(self.context, 123)

    def test_destroy(self):
        # The test harness needs db.service_destroy to work,
        # so avoid leaving it broken here after we're done
        orig_service_destroy = db.service_destroy
        try:
            self._test_destroy()
        finally:
            db.service_destroy = orig_service_destroy

    @mock.patch.object(db, 'service_get_all_by_topic',
                       return_value=[fake_service])
    def test_get_by_topic(self, mock_service_get):
        services = service.ServiceList.get_by_topic(self.context, 'fake-topic')
        self.assertEqual(1, len(services))
        self.compare_obj(services[0], fake_service, allow_missing=OPTIONAL)
        mock_service_get.assert_called_once_with(self.context, 'fake-topic')

    @mock.patch('nova.db.service_get_all_by_binary')
    def test_get_by_binary(self, mock_get):
        mock_get.return_value = [fake_service]
        services = service.ServiceList.get_by_binary(self.context,
                                                     'fake-binary')
        self.assertEqual(1, len(services))
        mock_get.assert_called_once_with(self.context,
                                         'fake-binary',
                                         include_disabled=False)

    @mock.patch('nova.db.service_get_all_by_binary')
    def test_get_by_binary_disabled(self, mock_get):
        mock_get.return_value = [_fake_service(disabled=True)]
        services = service.ServiceList.get_by_binary(self.context,
                                                     'fake-binary',
                                                     include_disabled=True)
        self.assertEqual(1, len(services))
        mock_get.assert_called_once_with(self.context,
                                         'fake-binary',
                                         include_disabled=True)

    @mock.patch('nova.db.service_get_all_by_binary')
    def test_get_by_binary_both(self, mock_get):
        mock_get.return_value = [_fake_service(),
                                 _fake_service(disabled=True)]
        services = service.ServiceList.get_by_binary(self.context,
                                                     'fake-binary',
                                                     include_disabled=True)
        self.assertEqual(2, len(services))
        mock_get.assert_called_once_with(self.context,
                                         'fake-binary',
                                         include_disabled=True)

    @mock.patch.object(db, 'service_get_all_by_host',
                       return_value=[fake_service])
    def test_get_by_host(self, mock_service_get):
        services = service.ServiceList.get_by_host(self.context, 'fake-host')
        self.assertEqual(1, len(services))
        self.compare_obj(services[0], fake_service, allow_missing=OPTIONAL)
        mock_service_get.assert_called_once_with(self.context, 'fake-host')

    @mock.patch.object(db, 'service_get_all', return_value=[fake_service])
    def test_get_all(self, mock_get_all):
        services = service.ServiceList.get_all(self.context, disabled=False)
        self.assertEqual(1, len(services))
        self.compare_obj(services[0], fake_service, allow_missing=OPTIONAL)
        mock_get_all.assert_called_once_with(self.context, disabled=False)

    @mock.patch.object(db, 'service_get_all')
    @mock.patch.object(aggregate.AggregateList, 'get_by_metadata_key')
    def test_get_all_with_az(self, mock_get_by_key, mock_get_all):
        agg = aggregate.Aggregate(context=self.context)
        agg.name = 'foo'
        agg.metadata = {'availability_zone': 'test-az'}
        agg.create()
        agg.hosts = [fake_service['host']]
        mock_get_by_key.return_value = [agg]
        mock_get_all.return_value = [dict(fake_service, topic='compute')]
        services = service.ServiceList.get_all(self.context, set_zones=True)
        self.assertEqual(1, len(services))
        self.assertEqual('test-az', services[0].availability_zone)
        mock_get_all.assert_called_once_with(self.context, disabled=None)
        mock_get_by_key.assert_called_once_with(self.context,
                         'availability_zone', hosts=set(agg.hosts))

    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host')
    def test_compute_node(self, mock_get):
        fake_compute_node = objects.ComputeNode._from_db_object(
            self.context, objects.ComputeNode(),
            test_compute_node.fake_compute_node)
        mock_get.return_value = [fake_compute_node]
        service_obj = service.Service(id=123, host="fake-host",
                                      binary="nova-compute")
        service_obj._context = self.context
        self.assertEqual(service_obj.compute_node,
                         fake_compute_node)
        # Make sure it doesn't re-fetch this
        service_obj.compute_node
        mock_get.assert_called_once_with(self.context, 'fake-host')

    @mock.patch.object(db, 'service_get_all_computes_by_hv_type')
    def test_get_all_computes_by_hv_type(self, mock_get_all):
        mock_get_all.return_value = [fake_service]
        services = service.ServiceList.get_all_computes_by_hv_type(
            self.context, 'hv-type')
        self.assertEqual(1, len(services))
        self.compare_obj(services[0], fake_service, allow_missing=OPTIONAL)
        mock_get_all.assert_called_once_with(self.context, 'hv-type',
                                             include_disabled=False)

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
        mock_get.assert_called_once_with(self.context, ['nova-compute'])

    @mock.patch('nova.db.service_get_minimum_version')
    def test_get_minimum_version(self, mock_get):
        mock_get.return_value = {'nova-compute': 123}
        self.assertEqual(123,
                         objects.Service.get_minimum_version(self.context,
                                                             'nova-compute'))
        mock_get.assert_called_once_with(self.context, ['nova-compute'])

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
        mock_get.return_value = {'nova-compute': 123}
        self.assertEqual(123,
                         objects.Service.get_minimum_version(self.context,
                                                             'nova-compute'))
        self.assertEqual({"nova-compute": 123},
                         objects.Service._MIN_VERSION_CACHE)
        self.assertEqual(123,
                         objects.Service.get_minimum_version(self.context,
                                                             'nova-compute'))
        mock_get.assert_called_once_with(self.context, ['nova-compute'])
        objects.Service._SERVICE_VERSION_CACHING = False
        objects.Service.clear_min_version_cache()

    @mock.patch('nova.db.service_get_minimum_version')
    def test_get_min_version_multiple_with_old(self, mock_gmv):
        mock_gmv.return_value = {'nova-api': None,
                                 'nova-scheduler': 2,
                                 'nova-conductor': 3}

        binaries = ['nova-api', 'nova-api', 'nova-conductor',
                    'nova-conductor', 'nova-api']
        minimum = objects.Service.get_minimum_version_multi(self.context,
                                                            binaries)
        self.assertEqual(0, minimum)

    @mock.patch('nova.db.service_get_minimum_version')
    def test_get_min_version_multiple(self, mock_gmv):
        mock_gmv.return_value = {'nova-api': 1,
                                 'nova-scheduler': 2,
                                 'nova-conductor': 3}

        binaries = ['nova-api', 'nova-api', 'nova-conductor',
                    'nova-conductor', 'nova-api']
        minimum = objects.Service.get_minimum_version_multi(self.context,
                                                            binaries)
        self.assertEqual(1, minimum)

    @mock.patch('nova.objects.Service._send_notification')
    @mock.patch('nova.db.service_get_minimum_version',
                return_value={'nova-compute': 2})
    def test_create_above_minimum(self, mock_get, mock_notify):
        with mock.patch('nova.objects.service.SERVICE_VERSION',
                        new=3):
            objects.Service(context=self.context,
                            binary='nova-compute').create()

    @mock.patch('nova.objects.Service._send_notification')
    @mock.patch('nova.db.service_get_minimum_version',
                return_value={'nova-compute': 2})
    def test_create_equal_to_minimum(self, mock_get, mock_notify):
        with mock.patch('nova.objects.service.SERVICE_VERSION',
                        new=2):
            objects.Service(context=self.context,
                            binary='nova-compute').create()

    @mock.patch('nova.db.service_get_minimum_version',
                return_value={'nova-compute': 2})
    def test_create_below_minimum(self, mock_get):
        with mock.patch('nova.objects.service.SERVICE_VERSION',
                        new=1):
            self.assertRaises(exception.ServiceTooOld,
                              objects.Service(context=self.context,
                                              binary='nova-compute',
                                              ).create)

    @mock.patch('nova.objects.base.NovaObject'
                '.obj_make_compatible_from_manifest', new=mock.Mock())
    def test_obj_make_compatible_from_manifest_strips_uuid(self):
        s = service.Service()
        primitive = {'uuid': uuidsentinel.service}
        s.obj_make_compatible_from_manifest(primitive, '1.20', mock.Mock())
        self.assertNotIn('uuid', primitive)

    @mock.patch('nova.objects.service.uuidutils.generate_uuid',
                return_value=uuidsentinel.service4)
    def test_from_db_object_without_uuid_generates_one(self, generate_uuid):
        values = _fake_service(uuid=None, id=None)
        db_service = db.api.service_create(self.context, values)

        s = service.Service()
        service.Service._from_db_object(self.context, s, db_service)
        self.assertEqual(uuidsentinel.service4, s.uuid)

        # Check the DB too
        db_service2 = db.api.service_get(self.context, s.id)
        self.assertEqual(s.uuid, db_service2['uuid'])


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
            'increment nova.objects.service.SERVICE_VERSION, and make sure it '
            'is equal to nova.compute.manager.ComputeManager.target.version.')

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


class TestServiceVersionCells(test.TestCase):

    def setUp(self):
        self.context = context.get_admin_context()
        super(TestServiceVersionCells, self).setUp()

    def _setup_cells(self):
        # NOTE(danms): Override the base class's cell setup so we can have two
        self.cells = fixtures.CellDatabases()
        self.cells.add_cell_database(uuidsentinel.cell1, default=True)
        self.cells.add_cell_database(uuidsentinel.cell2)
        self.useFixture(self.cells)

        cm = objects.CellMapping(context=self.context,
                                 uuid=uuidsentinel.cell1,
                                 name='cell1',
                                 transport_url='fake://nowhere/',
                                 database_connection=uuidsentinel.cell1)
        cm.create()
        cm = objects.CellMapping(context=self.context,
                                 uuid=uuidsentinel.cell2,
                                 name='cell2',
                                 transport_url='fake://nowhere/',
                                 database_connection=uuidsentinel.cell2)
        cm.create()

    def _create_services(self, *versions):
        cells = objects.CellMappingList.get_all(self.context)
        index = 0
        for version in versions:
            service = objects.Service(context=self.context,
                                      binary='nova-compute')
            service.version = version
            cell = cells[index % len(cells)]
            with context.target_cell(self.context, cell):
                service.create()
            index += 1

    @mock.patch('nova.objects.Service._send_notification')
    @mock.patch('nova.objects.Service._check_minimum_version')
    def test_version_all_cells(self, mock_check, mock_notify):
        self._create_services(16, 16, 13, 16)
        self.assertEqual(13, service.get_minimum_version_all_cells(
            self.context, ['nova-compute']))

    @mock.patch('nova.objects.service.LOG')
    def test_get_minimum_version_checks_binary(self, mock_log):
        ex = self.assertRaises(exception.ObjectActionError,
                               service.get_minimum_version_all_cells,
                               self.context, ['compute'])
        self.assertIn('Invalid binary prefix', six.text_type(ex))
        self.assertTrue(mock_log.warning.called)

    @mock.patch('nova.context.scatter_gather_all_cells')
    def test_version_all_cells_with_fail(self, mock_scatter):
        mock_scatter.return_value = {
            'foo': {'nova-compute': 13},
            'bar': context.raised_exception_sentinel,
        }
        self.assertEqual(13, service.get_minimum_version_all_cells(
            self.context, ['nova-compute']))
        self.assertRaises(exception.CellTimeout,
                          service.get_minimum_version_all_cells,
                          self.context, ['nova-compute'],
                          require_all=True)

    @mock.patch('nova.context.scatter_gather_all_cells')
    def test_version_all_cells_with_timeout(self, mock_scatter):
        mock_scatter.return_value = {
            'foo': {'nova-compute': 13},
            'bar': context.did_not_respond_sentinel,
        }
        self.assertEqual(13, service.get_minimum_version_all_cells(
            self.context, ['nova-compute']))
        self.assertRaises(exception.CellTimeout,
                          service.get_minimum_version_all_cells,
                          self.context, ['nova-compute'],
                          require_all=True)

    @mock.patch('nova.context.scatter_gather_all_cells')
    def test_version_all_cells_exclude_zero_service(self, mock_scatter):
        mock_scatter.return_value = {
            'foo': {'nova-compute': 13},
            'bar': {'nova-compute': 0},
        }
        self.assertEqual(13, service.get_minimum_version_all_cells(
            self.context, ['nova-compute']))
