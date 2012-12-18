# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

from nova import compute
from nova.compute import instance_types
from nova import context
from nova import db
from nova.db.sqlalchemy import api as sqa_api
from nova.db.sqlalchemy import models as sqa_models
from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import rpc
from nova.openstack.common import timeutils
from nova import quota
from nova.scheduler import driver as scheduler_driver
from nova import test
import nova.tests.image.fake

CONF = cfg.CONF
CONF.import_opt('scheduler_topic', 'nova.config')
CONF.import_opt('compute_driver', 'nova.virt.driver')


class QuotaIntegrationTestCase(test.TestCase):

    def setUp(self):
        super(QuotaIntegrationTestCase, self).setUp()
        self.flags(compute_driver='nova.virt.fake.FakeDriver',
                   quota_instances=2,
                   quota_cores=4,
                   quota_floating_ips=1,
                   network_manager='nova.network.manager.FlatDHCPManager')

        # Apparently needed by the RPC tests...
        self.network = self.start_service('network')

        self.user_id = 'admin'
        self.project_id = 'admin'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id,
                                              is_admin=True)
        orig_rpc_call = rpc.call

        def rpc_call_wrapper(context, topic, msg, timeout=None):
            """Stub out the scheduler creating the instance entry"""
            if (topic == CONF.scheduler_topic and
                msg['method'] == 'run_instance'):
                scheduler = scheduler_driver.Scheduler
                instance = scheduler().create_instance_db_entry(
                        context,
                        msg['args']['request_spec'],
                        None)
                return [scheduler_driver.encode_instance(instance)]
            else:
                return orig_rpc_call(context, topic, msg)

        self.stubs.Set(rpc, 'call', rpc_call_wrapper)
        nova.tests.image.fake.stub_out_image_service(self.stubs)

    def tearDown(self):
        super(QuotaIntegrationTestCase, self).tearDown()
        nova.tests.image.fake.FakeImageService_reset()

    def _create_instance(self, cores=2):
        """Create a test instance"""
        inst = {}
        inst['image_id'] = 'cedef40a-ed67-4d10-800e-17455edce175'
        inst['reservation_id'] = 'r-fakeres'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        inst['instance_type_id'] = '3'  # m1.large
        inst['vcpus'] = cores
        return db.instance_create(self.context, inst)

    def test_too_many_instances(self):
        instance_uuids = []
        for i in range(CONF.quota_instances):
            instance = self._create_instance()
            instance_uuids.append(instance['uuid'])
        inst_type = instance_types.get_instance_type_by_name('m1.small')
        image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
        self.assertRaises(exception.QuotaError, compute.API().create,
                                            self.context,
                                            min_count=1,
                                            max_count=1,
                                            instance_type=inst_type,
                                            image_href=image_uuid)
        for instance_uuid in instance_uuids:
            db.instance_destroy(self.context, instance_uuid)

    def test_too_many_cores(self):
        instance = self._create_instance(cores=4)
        inst_type = instance_types.get_instance_type_by_name('m1.small')
        image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
        self.assertRaises(exception.QuotaError, compute.API().create,
                                            self.context,
                                            min_count=1,
                                            max_count=1,
                                            instance_type=inst_type,
                                            image_href=image_uuid)
        db.instance_destroy(self.context, instance['uuid'])

    def test_too_many_addresses(self):
        address = '192.168.0.100'
        db.floating_ip_create(context.get_admin_context(),
                              {'address': address,
                               'project_id': self.project_id})
        self.assertRaises(exception.QuotaError,
                          self.network.allocate_floating_ip,
                          self.context,
                          self.project_id)
        db.floating_ip_destroy(context.get_admin_context(), address)

    def test_auto_assigned(self):
        address = '192.168.0.100'
        db.floating_ip_create(context.get_admin_context(),
                              {'address': address,
                               'project_id': self.project_id})
        # auto allocated addresses should not be counted
        self.assertRaises(exception.NoMoreFloatingIps,
                          self.network.allocate_floating_ip,
                          self.context,
                          self.project_id,
                          True)
        db.floating_ip_destroy(context.get_admin_context(), address)

    def test_too_many_metadata_items(self):
        metadata = {}
        for i in range(CONF.quota_metadata_items + 1):
            metadata['key%s' % i] = 'value%s' % i
        inst_type = instance_types.get_instance_type_by_name('m1.small')
        image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
        self.assertRaises(exception.QuotaError, compute.API().create,
                                            self.context,
                                            min_count=1,
                                            max_count=1,
                                            instance_type=inst_type,
                                            image_href=image_uuid,
                                            metadata=metadata)

    def _create_with_injected_files(self, files):
        api = compute.API()
        inst_type = instance_types.get_instance_type_by_name('m1.small')
        image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
        api.create(self.context, min_count=1, max_count=1,
                instance_type=inst_type, image_href=image_uuid,
                injected_files=files)

    def test_no_injected_files(self):
        api = compute.API()
        inst_type = instance_types.get_instance_type_by_name('m1.small')
        image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
        api.create(self.context,
                   instance_type=inst_type,
                   image_href=image_uuid)

    def test_max_injected_files(self):
        files = []
        for i in xrange(CONF.quota_injected_files):
            files.append(('/my/path%d' % i, 'config = test\n'))
        self._create_with_injected_files(files)  # no QuotaError

    def test_too_many_injected_files(self):
        files = []
        for i in xrange(CONF.quota_injected_files + 1):
            files.append(('/my/path%d' % i, 'my\ncontent%d\n' % i))
        self.assertRaises(exception.QuotaError,
                          self._create_with_injected_files, files)

    def test_max_injected_file_content_bytes(self):
        max = CONF.quota_injected_file_content_bytes
        content = ''.join(['a' for i in xrange(max)])
        files = [('/test/path', content)]
        self._create_with_injected_files(files)  # no QuotaError

    def test_too_many_injected_file_content_bytes(self):
        max = CONF.quota_injected_file_content_bytes
        content = ''.join(['a' for i in xrange(max + 1)])
        files = [('/test/path', content)]
        self.assertRaises(exception.QuotaError,
                          self._create_with_injected_files, files)

    def test_max_injected_file_path_bytes(self):
        max = CONF.quota_injected_file_path_bytes
        path = ''.join(['a' for i in xrange(max)])
        files = [(path, 'config = quotatest')]
        self._create_with_injected_files(files)  # no QuotaError

    def test_too_many_injected_file_path_bytes(self):
        max = CONF.quota_injected_file_path_bytes
        path = ''.join(['a' for i in xrange(max + 1)])
        files = [(path, 'config = quotatest')]
        self.assertRaises(exception.QuotaError,
                          self._create_with_injected_files, files)

    def test_reservation_expire(self):
        self.useFixture(test.TimeOverride())

        def assertInstancesReserved(reserved):
            result = quota.QUOTAS.get_project_quotas(self.context,
                                                     self.context.project_id)
            self.assertEqual(result['instances']['reserved'], reserved)

        quota.QUOTAS.reserve(self.context,
                             expire=60,
                             instances=2)

        assertInstancesReserved(2)

        timeutils.advance_time_seconds(80)

        result = quota.QUOTAS.expire(self.context)

        assertInstancesReserved(0)


class FakeContext(object):
    def __init__(self, project_id, quota_class):
        self.is_admin = False
        self.user_id = 'fake_user'
        self.project_id = project_id
        self.quota_class = quota_class

    def elevated(self):
        elevated = self.__class__(self.project_id, self.quota_class)
        elevated.is_admin = True
        return elevated


class FakeDriver(object):
    def __init__(self, by_project=None, by_class=None, reservations=None):
        self.called = []
        self.by_project = by_project or {}
        self.by_class = by_class or {}
        self.reservations = reservations or []

    def get_by_project(self, context, project_id, resource):
        self.called.append(('get_by_project', context, project_id, resource))
        try:
            return self.by_project[project_id][resource]
        except KeyError:
            raise exception.ProjectQuotaNotFound(project_id=project_id)

    def get_by_class(self, context, quota_class, resource):
        self.called.append(('get_by_class', context, quota_class, resource))
        try:
            return self.by_class[quota_class][resource]
        except KeyError:
            raise exception.QuotaClassNotFound(class_name=quota_class)

    def get_defaults(self, context, resources):
        self.called.append(('get_defaults', context, resources))
        return resources

    def get_class_quotas(self, context, resources, quota_class,
                         defaults=True):
        self.called.append(('get_class_quotas', context, resources,
                            quota_class, defaults))
        return resources

    def get_project_quotas(self, context, resources, project_id,
                           quota_class=None, defaults=True, usages=True):
        self.called.append(('get_project_quotas', context, resources,
                            project_id, quota_class, defaults, usages))
        return resources

    def limit_check(self, context, resources, values):
        self.called.append(('limit_check', context, resources, values))

    def reserve(self, context, resources, deltas, expire=None):
        self.called.append(('reserve', context, resources, deltas, expire))
        return self.reservations

    def commit(self, context, reservations):
        self.called.append(('commit', context, reservations))

    def rollback(self, context, reservations):
        self.called.append(('rollback', context, reservations))

    def usage_reset(self, context, resources):
        self.called.append(('usage_reset', context, resources))

    def destroy_all_by_project(self, context, project_id):
        self.called.append(('destroy_all_by_project', context, project_id))

    def expire(self, context):
        self.called.append(('expire', context))


class BaseResourceTestCase(test.TestCase):
    def test_no_flag(self):
        resource = quota.BaseResource('test_resource')

        self.assertEqual(resource.name, 'test_resource')
        self.assertEqual(resource.flag, None)
        self.assertEqual(resource.default, -1)

    def test_with_flag(self):
        # We know this flag exists, so use it...
        self.flags(quota_instances=10)
        resource = quota.BaseResource('test_resource', 'quota_instances')

        self.assertEqual(resource.name, 'test_resource')
        self.assertEqual(resource.flag, 'quota_instances')
        self.assertEqual(resource.default, 10)

    def test_with_flag_no_quota(self):
        self.flags(quota_instances=-1)
        resource = quota.BaseResource('test_resource', 'quota_instances')

        self.assertEqual(resource.name, 'test_resource')
        self.assertEqual(resource.flag, 'quota_instances')
        self.assertEqual(resource.default, -1)

    def test_quota_no_project_no_class(self):
        self.flags(quota_instances=10)
        resource = quota.BaseResource('test_resource', 'quota_instances')
        driver = FakeDriver()
        context = FakeContext(None, None)
        quota_value = resource.quota(driver, context)

        self.assertEqual(quota_value, 10)

    def test_quota_with_project_no_class(self):
        self.flags(quota_instances=10)
        resource = quota.BaseResource('test_resource', 'quota_instances')
        driver = FakeDriver(by_project=dict(
                test_project=dict(test_resource=15),
                ))
        context = FakeContext('test_project', None)
        quota_value = resource.quota(driver, context)

        self.assertEqual(quota_value, 15)

    def test_quota_no_project_with_class(self):
        self.flags(quota_instances=10)
        resource = quota.BaseResource('test_resource', 'quota_instances')
        driver = FakeDriver(by_class=dict(
                test_class=dict(test_resource=20),
                ))
        context = FakeContext(None, 'test_class')
        quota_value = resource.quota(driver, context)

        self.assertEqual(quota_value, 20)

    def test_quota_with_project_with_class(self):
        self.flags(quota_instances=10)
        resource = quota.BaseResource('test_resource', 'quota_instances')
        driver = FakeDriver(by_project=dict(
                test_project=dict(test_resource=15),
                ),
                            by_class=dict(
                test_class=dict(test_resource=20),
                ))
        context = FakeContext('test_project', 'test_class')
        quota_value = resource.quota(driver, context)

        self.assertEqual(quota_value, 15)

    def test_quota_override_project_with_class(self):
        self.flags(quota_instances=10)
        resource = quota.BaseResource('test_resource', 'quota_instances')
        driver = FakeDriver(by_project=dict(
                test_project=dict(test_resource=15),
                override_project=dict(test_resource=20),
                ))
        context = FakeContext('test_project', 'test_class')
        quota_value = resource.quota(driver, context,
                                     project_id='override_project')

        self.assertEqual(quota_value, 20)

    def test_quota_with_project_override_class(self):
        self.flags(quota_instances=10)
        resource = quota.BaseResource('test_resource', 'quota_instances')
        driver = FakeDriver(by_class=dict(
                test_class=dict(test_resource=15),
                override_class=dict(test_resource=20),
                ))
        context = FakeContext('test_project', 'test_class')
        quota_value = resource.quota(driver, context,
                                     quota_class='override_class')

        self.assertEqual(quota_value, 20)


class QuotaEngineTestCase(test.TestCase):
    def test_init(self):
        quota_obj = quota.QuotaEngine()

        self.assertEqual(quota_obj._resources, {})
        self.assertTrue(isinstance(quota_obj._driver, quota.DbQuotaDriver))

    def test_init_override_string(self):
        quota_obj = quota.QuotaEngine(
            quota_driver_class='nova.tests.test_quota.FakeDriver')

        self.assertEqual(quota_obj._resources, {})
        self.assertTrue(isinstance(quota_obj._driver, FakeDriver))

    def test_init_override_obj(self):
        quota_obj = quota.QuotaEngine(quota_driver_class=FakeDriver)

        self.assertEqual(quota_obj._resources, {})
        self.assertEqual(quota_obj._driver, FakeDriver)

    def test_register_resource(self):
        quota_obj = quota.QuotaEngine()
        resource = quota.AbsoluteResource('test_resource')
        quota_obj.register_resource(resource)

        self.assertEqual(quota_obj._resources, dict(test_resource=resource))

    def test_register_resources(self):
        quota_obj = quota.QuotaEngine()
        resources = [
            quota.AbsoluteResource('test_resource1'),
            quota.AbsoluteResource('test_resource2'),
            quota.AbsoluteResource('test_resource3'),
            ]
        quota_obj.register_resources(resources)

        self.assertEqual(quota_obj._resources, dict(
                test_resource1=resources[0],
                test_resource2=resources[1],
                test_resource3=resources[2],
                ))

    def test_sync_predeclared(self):
        quota_obj = quota.QuotaEngine()

        def spam(*args, **kwargs):
            pass

        resource = quota.ReservableResource('test_resource', spam)
        quota_obj.register_resource(resource)

        self.assertEqual(resource.sync, spam)

    def test_sync_multi(self):
        quota_obj = quota.QuotaEngine()

        def spam(*args, **kwargs):
            pass

        resources = [
            quota.ReservableResource('test_resource1', spam),
            quota.ReservableResource('test_resource2', spam),
            quota.ReservableResource('test_resource3', spam),
            quota.ReservableResource('test_resource4', spam),
            ]
        quota_obj.register_resources(resources[:2])

        self.assertEqual(resources[0].sync, spam)
        self.assertEqual(resources[1].sync, spam)
        self.assertEqual(resources[2].sync, spam)
        self.assertEqual(resources[3].sync, spam)

    def test_get_by_project(self):
        context = FakeContext('test_project', 'test_class')
        driver = FakeDriver(by_project=dict(
                test_project=dict(test_resource=42)))
        quota_obj = quota.QuotaEngine(quota_driver_class=driver)
        result = quota_obj.get_by_project(context, 'test_project',
                                          'test_resource')

        self.assertEqual(driver.called, [
                ('get_by_project', context, 'test_project', 'test_resource'),
                ])
        self.assertEqual(result, 42)

    def test_get_by_class(self):
        context = FakeContext('test_project', 'test_class')
        driver = FakeDriver(by_class=dict(
                test_class=dict(test_resource=42)))
        quota_obj = quota.QuotaEngine(quota_driver_class=driver)
        result = quota_obj.get_by_class(context, 'test_class', 'test_resource')

        self.assertEqual(driver.called, [
                ('get_by_class', context, 'test_class', 'test_resource'),
                ])
        self.assertEqual(result, 42)

    def _make_quota_obj(self, driver):
        quota_obj = quota.QuotaEngine(quota_driver_class=driver)
        resources = [
            quota.AbsoluteResource('test_resource4'),
            quota.AbsoluteResource('test_resource3'),
            quota.AbsoluteResource('test_resource2'),
            quota.AbsoluteResource('test_resource1'),
            ]
        quota_obj.register_resources(resources)

        return quota_obj

    def test_get_defaults(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        result = quota_obj.get_defaults(context)

        self.assertEqual(driver.called, [
                ('get_defaults', context, quota_obj._resources),
                ])
        self.assertEqual(result, quota_obj._resources)

    def test_get_class_quotas(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        result1 = quota_obj.get_class_quotas(context, 'test_class')
        result2 = quota_obj.get_class_quotas(context, 'test_class', False)

        self.assertEqual(driver.called, [
                ('get_class_quotas', context, quota_obj._resources,
                 'test_class', True),
                ('get_class_quotas', context, quota_obj._resources,
                 'test_class', False),
                ])
        self.assertEqual(result1, quota_obj._resources)
        self.assertEqual(result2, quota_obj._resources)

    def test_get_project_quotas(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        result1 = quota_obj.get_project_quotas(context, 'test_project')
        result2 = quota_obj.get_project_quotas(context, 'test_project',
                                               quota_class='test_class',
                                               defaults=False,
                                               usages=False)

        self.assertEqual(driver.called, [
                ('get_project_quotas', context, quota_obj._resources,
                 'test_project', None, True, True),
                ('get_project_quotas', context, quota_obj._resources,
                 'test_project', 'test_class', False, False),
                ])
        self.assertEqual(result1, quota_obj._resources)
        self.assertEqual(result2, quota_obj._resources)

    def test_count_no_resource(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        self.assertRaises(exception.QuotaResourceUnknown,
                          quota_obj.count, context, 'test_resource5',
                          True, foo='bar')

    def test_count_wrong_resource(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        self.assertRaises(exception.QuotaResourceUnknown,
                          quota_obj.count, context, 'test_resource1',
                          True, foo='bar')

    def test_count(self):
        def fake_count(context, *args, **kwargs):
            self.assertEqual(args, (True,))
            self.assertEqual(kwargs, dict(foo='bar'))
            return 5

        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.register_resource(quota.CountableResource('test_resource5',
                                                            fake_count))
        result = quota_obj.count(context, 'test_resource5', True, foo='bar')

        self.assertEqual(result, 5)

    def test_limit_check(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.limit_check(context, test_resource1=4, test_resource2=3,
                              test_resource3=2, test_resource4=1)

        self.assertEqual(driver.called, [
                ('limit_check', context, quota_obj._resources, dict(
                        test_resource1=4,
                        test_resource2=3,
                        test_resource3=2,
                        test_resource4=1,
                        )),
                ])

    def test_reserve(self):
        context = FakeContext(None, None)
        driver = FakeDriver(reservations=[
                'resv-01', 'resv-02', 'resv-03', 'resv-04',
                ])
        quota_obj = self._make_quota_obj(driver)
        result1 = quota_obj.reserve(context, test_resource1=4,
                                    test_resource2=3, test_resource3=2,
                                    test_resource4=1)
        result2 = quota_obj.reserve(context, expire=3600,
                                    test_resource1=1, test_resource2=2,
                                    test_resource3=3, test_resource4=4)

        self.assertEqual(driver.called, [
                ('reserve', context, quota_obj._resources, dict(
                        test_resource1=4,
                        test_resource2=3,
                        test_resource3=2,
                        test_resource4=1,
                        ), None),
                ('reserve', context, quota_obj._resources, dict(
                        test_resource1=1,
                        test_resource2=2,
                        test_resource3=3,
                        test_resource4=4,
                        ), 3600),
                ])
        self.assertEqual(result1, [
                'resv-01', 'resv-02', 'resv-03', 'resv-04',
                ])
        self.assertEqual(result2, [
                'resv-01', 'resv-02', 'resv-03', 'resv-04',
                ])

    def test_commit(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.commit(context, ['resv-01', 'resv-02', 'resv-03'])

        self.assertEqual(driver.called, [
                ('commit', context, ['resv-01', 'resv-02', 'resv-03']),
                ])

    def test_rollback(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.rollback(context, ['resv-01', 'resv-02', 'resv-03'])

        self.assertEqual(driver.called, [
                ('rollback', context, ['resv-01', 'resv-02', 'resv-03']),
                ])

    def test_usage_reset(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.usage_reset(context, ['res1', 'res2', 'res3'])

        self.assertEqual(driver.called, [
                ('usage_reset', context, ['res1', 'res2', 'res3']),
                ])

    def test_destroy_all_by_project(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.destroy_all_by_project(context, 'test_project')

        self.assertEqual(driver.called, [
                ('destroy_all_by_project', context, 'test_project'),
                ])

    def test_expire(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.expire(context)

        self.assertEqual(driver.called, [
                ('expire', context),
                ])

    def test_resources(self):
        quota_obj = self._make_quota_obj(None)

        self.assertEqual(quota_obj.resources,
                         ['test_resource1', 'test_resource2',
                          'test_resource3', 'test_resource4'])


class DbQuotaDriverTestCase(test.TestCase):
    def setUp(self):
        super(DbQuotaDriverTestCase, self).setUp()

        self.flags(quota_instances=10,
                   quota_cores=20,
                   quota_ram=50 * 1024,
                   quota_floating_ips=10,
                   quota_metadata_items=128,
                   quota_injected_files=5,
                   quota_injected_file_content_bytes=10 * 1024,
                   quota_injected_file_path_bytes=255,
                   quota_security_groups=10,
                   quota_security_group_rules=20,
                   reservation_expire=86400,
                   until_refresh=0,
                   max_age=0,
                   )

        self.driver = quota.DbQuotaDriver()

        self.calls = []

        self.useFixture(test.TimeOverride())

    def test_get_defaults(self):
        # Use our pre-defined resources
        result = self.driver.get_defaults(None, quota.QUOTAS._resources)

        self.assertEqual(result, dict(
                instances=10,
                cores=20,
                ram=50 * 1024,
                floating_ips=10,
                metadata_items=128,
                injected_files=5,
                injected_file_content_bytes=10 * 1024,
                injected_file_path_bytes=255,
                security_groups=10,
                security_group_rules=20,
                key_pairs=100,
                ))

    def _stub_quota_class_get_all_by_name(self):
        # Stub out quota_class_get_all_by_name
        def fake_qcgabn(context, quota_class):
            self.calls.append('quota_class_get_all_by_name')
            self.assertEqual(quota_class, 'test_class')
            return dict(
                instances=5,
                ram=25 * 1024,
                metadata_items=64,
                injected_file_content_bytes=5 * 1024,
                )
        self.stubs.Set(db, 'quota_class_get_all_by_name', fake_qcgabn)

    def test_get_class_quotas(self):
        self._stub_quota_class_get_all_by_name()
        result = self.driver.get_class_quotas(None, quota.QUOTAS._resources,
                                              'test_class')

        self.assertEqual(self.calls, ['quota_class_get_all_by_name'])
        self.assertEqual(result, dict(
                instances=5,
                cores=20,
                ram=25 * 1024,
                floating_ips=10,
                metadata_items=64,
                injected_files=5,
                injected_file_content_bytes=5 * 1024,
                injected_file_path_bytes=255,
                security_groups=10,
                security_group_rules=20,
                key_pairs=100,
                ))

    def test_get_class_quotas_no_defaults(self):
        self._stub_quota_class_get_all_by_name()
        result = self.driver.get_class_quotas(None, quota.QUOTAS._resources,
                                              'test_class', False)

        self.assertEqual(self.calls, ['quota_class_get_all_by_name'])
        self.assertEqual(result, dict(
                instances=5,
                ram=25 * 1024,
                metadata_items=64,
                injected_file_content_bytes=5 * 1024,
                ))

    def _stub_get_by_project(self):
        def fake_qgabp(context, project_id):
            self.calls.append('quota_get_all_by_project')
            self.assertEqual(project_id, 'test_project')
            return dict(
                cores=10,
                injected_files=2,
                injected_file_path_bytes=127,
                )

        def fake_qugabp(context, project_id):
            self.calls.append('quota_usage_get_all_by_project')
            self.assertEqual(project_id, 'test_project')
            return dict(
                instances=dict(in_use=2, reserved=2),
                cores=dict(in_use=4, reserved=4),
                ram=dict(in_use=10 * 1024, reserved=0),
                floating_ips=dict(in_use=2, reserved=0),
                metadata_items=dict(in_use=0, reserved=0),
                injected_files=dict(in_use=0, reserved=0),
                injected_file_content_bytes=dict(in_use=0, reserved=0),
                injected_file_path_bytes=dict(in_use=0, reserved=0),
                )

        self.stubs.Set(db, 'quota_get_all_by_project', fake_qgabp)
        self.stubs.Set(db, 'quota_usage_get_all_by_project', fake_qugabp)

        self._stub_quota_class_get_all_by_name()

    def test_get_project_quotas(self):
        self._stub_get_by_project()
        result = self.driver.get_project_quotas(
            FakeContext('test_project', 'test_class'),
            quota.QUOTAS._resources, 'test_project')

        self.assertEqual(self.calls, [
                'quota_get_all_by_project',
                'quota_usage_get_all_by_project',
                'quota_class_get_all_by_name',
                ])
        self.assertEqual(result, dict(
                instances=dict(
                    limit=5,
                    in_use=2,
                    reserved=2,
                    ),
                cores=dict(
                    limit=10,
                    in_use=4,
                    reserved=4,
                    ),
                ram=dict(
                    limit=25 * 1024,
                    in_use=10 * 1024,
                    reserved=0,
                    ),
               floating_ips=dict(
                    limit=10,
                    in_use=2,
                    reserved=0,
                    ),
                metadata_items=dict(
                    limit=64,
                    in_use=0,
                    reserved=0,
                    ),
                injected_files=dict(
                    limit=2,
                    in_use=0,
                    reserved=0,
                    ),
                injected_file_content_bytes=dict(
                    limit=5 * 1024,
                    in_use=0,
                    reserved=0,
                    ),
                injected_file_path_bytes=dict(
                    limit=127,
                    in_use=0,
                    reserved=0,
                    ),
                security_groups=dict(
                    limit=10,
                    in_use=0,
                    reserved=0,
                    ),
                security_group_rules=dict(
                    limit=20,
                    in_use=0,
                    reserved=0,
                    ),
                key_pairs=dict(
                    limit=100,
                    in_use=0,
                    reserved=0,
                    ),
                ))

    def test_get_project_quotas_alt_context_no_class(self):
        self._stub_get_by_project()
        result = self.driver.get_project_quotas(
            FakeContext('other_project', 'other_class'),
            quota.QUOTAS._resources, 'test_project')

        self.assertEqual(self.calls, [
                'quota_get_all_by_project',
                'quota_usage_get_all_by_project',
                ])
        self.assertEqual(result, dict(
                instances=dict(
                    limit=10,
                    in_use=2,
                    reserved=2,
                    ),
                cores=dict(
                    limit=10,
                    in_use=4,
                    reserved=4,
                    ),
                ram=dict(
                    limit=50 * 1024,
                    in_use=10 * 1024,
                    reserved=0,
                    ),
               floating_ips=dict(
                    limit=10,
                    in_use=2,
                    reserved=0,
                    ),
                metadata_items=dict(
                    limit=128,
                    in_use=0,
                    reserved=0,
                    ),
                injected_files=dict(
                    limit=2,
                    in_use=0,
                    reserved=0,
                    ),
                injected_file_content_bytes=dict(
                    limit=10 * 1024,
                    in_use=0,
                    reserved=0,
                    ),
                injected_file_path_bytes=dict(
                    limit=127,
                    in_use=0,
                    reserved=0,
                    ),
                security_groups=dict(
                    limit=10,
                    in_use=0,
                    reserved=0,
                    ),
                security_group_rules=dict(
                    limit=20,
                    in_use=0,
                    reserved=0,
                    ),
                key_pairs=dict(
                    limit=100,
                    in_use=0,
                    reserved=0,
                    ),
                ))

    def test_get_project_quotas_alt_context_with_class(self):
        self._stub_get_by_project()
        result = self.driver.get_project_quotas(
            FakeContext('other_project', 'other_class'),
            quota.QUOTAS._resources, 'test_project', quota_class='test_class')

        self.assertEqual(self.calls, [
                'quota_get_all_by_project',
                'quota_usage_get_all_by_project',
                'quota_class_get_all_by_name',
                ])
        self.assertEqual(result, dict(
                instances=dict(
                    limit=5,
                    in_use=2,
                    reserved=2,
                    ),
                cores=dict(
                    limit=10,
                    in_use=4,
                    reserved=4,
                    ),
                ram=dict(
                    limit=25 * 1024,
                    in_use=10 * 1024,
                    reserved=0,
                    ),
                floating_ips=dict(
                    limit=10,
                    in_use=2,
                    reserved=0,
                    ),
                metadata_items=dict(
                    limit=64,
                    in_use=0,
                    reserved=0,
                    ),
                injected_files=dict(
                    limit=2,
                    in_use=0,
                    reserved=0,
                    ),
                injected_file_content_bytes=dict(
                    limit=5 * 1024,
                    in_use=0,
                    reserved=0,
                    ),
                injected_file_path_bytes=dict(
                    limit=127,
                    in_use=0,
                    reserved=0,
                    ),
                security_groups=dict(
                    limit=10,
                    in_use=0,
                    reserved=0,
                    ),
                security_group_rules=dict(
                    limit=20,
                    in_use=0,
                    reserved=0,
                    ),
                key_pairs=dict(
                    limit=100,
                    in_use=0,
                    reserved=0,
                    ),
                ))

    def test_get_project_quotas_no_defaults(self):
        self._stub_get_by_project()
        result = self.driver.get_project_quotas(
            FakeContext('test_project', 'test_class'),
            quota.QUOTAS._resources, 'test_project', defaults=False)

        self.assertEqual(self.calls, [
                'quota_get_all_by_project',
                'quota_usage_get_all_by_project',
                'quota_class_get_all_by_name',
                ])
        self.assertEqual(result, dict(
                cores=dict(
                    limit=10,
                    in_use=4,
                    reserved=4,
                    ),
               injected_files=dict(
                    limit=2,
                    in_use=0,
                    reserved=0,
                    ),
                injected_file_path_bytes=dict(
                    limit=127,
                    in_use=0,
                    reserved=0,
                    ),
                ))

    def test_get_project_quotas_no_usages(self):
        self._stub_get_by_project()
        result = self.driver.get_project_quotas(
            FakeContext('test_project', 'test_class'),
            quota.QUOTAS._resources, 'test_project', usages=False)

        self.assertEqual(self.calls, [
                'quota_get_all_by_project',
                'quota_class_get_all_by_name',
                ])
        self.assertEqual(result, dict(
                instances=dict(
                    limit=5,
                    ),
                cores=dict(
                    limit=10,
                    ),
                ram=dict(
                    limit=25 * 1024,
                    ),
                floating_ips=dict(
                    limit=10,
                    ),
                metadata_items=dict(
                    limit=64,
                    ),
                injected_files=dict(
                    limit=2,
                    ),
                injected_file_content_bytes=dict(
                    limit=5 * 1024,
                    ),
                injected_file_path_bytes=dict(
                    limit=127,
                    ),
                security_groups=dict(
                    limit=10,
                    ),
                security_group_rules=dict(
                    limit=20,
                    ),
                key_pairs=dict(
                    limit=100,
                    ),
                ))

    def _stub_get_project_quotas(self):
        def fake_get_project_quotas(context, resources, project_id,
                                    quota_class=None, defaults=True,
                                    usages=True):
            self.calls.append('get_project_quotas')
            return dict((k, dict(limit=v.default))
                        for k, v in resources.items())

        self.stubs.Set(self.driver, 'get_project_quotas',
                       fake_get_project_quotas)

    def test_get_quotas_has_sync_unknown(self):
        self._stub_get_project_quotas()
        self.assertRaises(exception.QuotaResourceUnknown,
                          self.driver._get_quotas,
                          None, quota.QUOTAS._resources,
                          ['unknown'], True)
        self.assertEqual(self.calls, [])

    def test_get_quotas_no_sync_unknown(self):
        self._stub_get_project_quotas()
        self.assertRaises(exception.QuotaResourceUnknown,
                          self.driver._get_quotas,
                          None, quota.QUOTAS._resources,
                          ['unknown'], False)
        self.assertEqual(self.calls, [])

    def test_get_quotas_has_sync_no_sync_resource(self):
        self._stub_get_project_quotas()
        self.assertRaises(exception.QuotaResourceUnknown,
                          self.driver._get_quotas,
                          None, quota.QUOTAS._resources,
                          ['metadata_items'], True)
        self.assertEqual(self.calls, [])

    def test_get_quotas_no_sync_has_sync_resource(self):
        self._stub_get_project_quotas()
        self.assertRaises(exception.QuotaResourceUnknown,
                          self.driver._get_quotas,
                          None, quota.QUOTAS._resources,
                          ['instances'], False)
        self.assertEqual(self.calls, [])

    def test_get_quotas_has_sync(self):
        self._stub_get_project_quotas()
        result = self.driver._get_quotas(FakeContext('test_project',
                                                     'test_class'),
                                         quota.QUOTAS._resources,
                                         ['instances', 'cores', 'ram',
                                          'floating_ips', 'security_groups'],
                                         True)

        self.assertEqual(self.calls, ['get_project_quotas'])
        self.assertEqual(result, dict(
                instances=10,
                cores=20,
                ram=50 * 1024,
                floating_ips=10,
                security_groups=10,
                ))

    def test_get_quotas_no_sync(self):
        self._stub_get_project_quotas()
        result = self.driver._get_quotas(FakeContext('test_project',
                                                     'test_class'),
                                         quota.QUOTAS._resources,
                                         ['metadata_items', 'injected_files',
                                          'injected_file_content_bytes',
                                          'injected_file_path_bytes',
                                          'security_group_rules'], False)

        self.assertEqual(self.calls, ['get_project_quotas'])
        self.assertEqual(result, dict(
                metadata_items=128,
                injected_files=5,
                injected_file_content_bytes=10 * 1024,
                injected_file_path_bytes=255,
                security_group_rules=20,
                ))

    def test_limit_check_under(self):
        self._stub_get_project_quotas()
        self.assertRaises(exception.InvalidQuotaValue,
                          self.driver.limit_check,
                          FakeContext('test_project', 'test_class'),
                          quota.QUOTAS._resources,
                          dict(metadata_items=-1))

    def test_limit_check_over(self):
        self._stub_get_project_quotas()
        self.assertRaises(exception.OverQuota,
                          self.driver.limit_check,
                          FakeContext('test_project', 'test_class'),
                          quota.QUOTAS._resources,
                          dict(metadata_items=129))

    def test_limit_check_unlimited(self):
        self.flags(quota_metadata_items=-1)
        self._stub_get_project_quotas()
        self.driver.limit_check(FakeContext('test_project', 'test_class'),
                                quota.QUOTAS._resources,
                                dict(metadata_items=32767))

    def test_limit_check(self):
        self._stub_get_project_quotas()
        self.driver.limit_check(FakeContext('test_project', 'test_class'),
                                quota.QUOTAS._resources,
                                dict(metadata_items=128))

    def _stub_quota_reserve(self):
        def fake_quota_reserve(context, resources, quotas, deltas, expire,
                               until_refresh, max_age):
            self.calls.append(('quota_reserve', expire, until_refresh,
                               max_age))
            return ['resv-1', 'resv-2', 'resv-3']
        self.stubs.Set(db, 'quota_reserve', fake_quota_reserve)

    def test_reserve_bad_expire(self):
        self._stub_get_project_quotas()
        self._stub_quota_reserve()
        self.assertRaises(exception.InvalidReservationExpiration,
                          self.driver.reserve,
                          FakeContext('test_project', 'test_class'),
                          quota.QUOTAS._resources,
                          dict(instances=2), expire='invalid')
        self.assertEqual(self.calls, [])

    def test_reserve_default_expire(self):
        self._stub_get_project_quotas()
        self._stub_quota_reserve()
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS._resources,
                                     dict(instances=2))

        expire = timeutils.utcnow() + datetime.timedelta(seconds=86400)
        self.assertEqual(self.calls, [
                'get_project_quotas',
                ('quota_reserve', expire, 0, 0),
                ])
        self.assertEqual(result, ['resv-1', 'resv-2', 'resv-3'])

    def test_reserve_int_expire(self):
        self._stub_get_project_quotas()
        self._stub_quota_reserve()
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS._resources,
                                     dict(instances=2), expire=3600)

        expire = timeutils.utcnow() + datetime.timedelta(seconds=3600)
        self.assertEqual(self.calls, [
                'get_project_quotas',
                ('quota_reserve', expire, 0, 0),
                ])
        self.assertEqual(result, ['resv-1', 'resv-2', 'resv-3'])

    def test_reserve_timedelta_expire(self):
        self._stub_get_project_quotas()
        self._stub_quota_reserve()
        expire_delta = datetime.timedelta(seconds=60)
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS._resources,
                                     dict(instances=2), expire=expire_delta)

        expire = timeutils.utcnow() + expire_delta
        self.assertEqual(self.calls, [
                'get_project_quotas',
                ('quota_reserve', expire, 0, 0),
                ])
        self.assertEqual(result, ['resv-1', 'resv-2', 'resv-3'])

    def test_reserve_datetime_expire(self):
        self._stub_get_project_quotas()
        self._stub_quota_reserve()
        expire = timeutils.utcnow() + datetime.timedelta(seconds=120)
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS._resources,
                                     dict(instances=2), expire=expire)

        self.assertEqual(self.calls, [
                'get_project_quotas',
                ('quota_reserve', expire, 0, 0),
                ])
        self.assertEqual(result, ['resv-1', 'resv-2', 'resv-3'])

    def test_reserve_until_refresh(self):
        self._stub_get_project_quotas()
        self._stub_quota_reserve()
        self.flags(until_refresh=500)
        expire = timeutils.utcnow() + datetime.timedelta(seconds=120)
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS._resources,
                                     dict(instances=2), expire=expire)

        self.assertEqual(self.calls, [
                'get_project_quotas',
                ('quota_reserve', expire, 500, 0),
                ])
        self.assertEqual(result, ['resv-1', 'resv-2', 'resv-3'])

    def test_reserve_max_age(self):
        self._stub_get_project_quotas()
        self._stub_quota_reserve()
        self.flags(max_age=86400)
        expire = timeutils.utcnow() + datetime.timedelta(seconds=120)
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS._resources,
                                     dict(instances=2), expire=expire)

        self.assertEqual(self.calls, [
                'get_project_quotas',
                ('quota_reserve', expire, 0, 86400),
                ])
        self.assertEqual(result, ['resv-1', 'resv-2', 'resv-3'])

    def test_usage_reset(self):
        calls = []

        def fake_quota_usage_update(context, project_id, resource, **kwargs):
            calls.append(('quota_usage_update', context, project_id,
                          resource, kwargs))
            if resource == 'nonexist':
                raise exception.QuotaUsageNotFound()
        self.stubs.Set(db, 'quota_usage_update', fake_quota_usage_update)

        ctx = FakeContext('test_project', 'test_class')
        resources = ['res1', 'res2', 'nonexist', 'res4']
        self.driver.usage_reset(ctx, resources)

        # Make sure we had some calls
        self.assertEqual(len(calls), len(resources))

        # Extract the elevated context that was used and do some
        # sanity checks
        elevated = calls[0][1]
        self.assertEqual(elevated.project_id, ctx.project_id)
        self.assertEqual(elevated.quota_class, ctx.quota_class)
        self.assertEqual(elevated.is_admin, True)

        # Now check that all the expected calls were made
        exemplar = [('quota_usage_update', elevated, 'test_project',
                     res, dict(in_use=-1)) for res in resources]
        self.assertEqual(calls, exemplar)


class FakeSession(object):
    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        return False


class FakeUsage(sqa_models.QuotaUsage):
    def save(self, *args, **kwargs):
        pass


class QuotaReserveSqlAlchemyTestCase(test.TestCase):
    # nova.db.sqlalchemy.api.quota_reserve is so complex it needs its
    # own test case, and since it's a quota manipulator, this is the
    # best place to put it...

    def setUp(self):
        super(QuotaReserveSqlAlchemyTestCase, self).setUp()

        self.sync_called = set()

        def make_sync(res_name):
            def sync(context, project_id, session):
                self.sync_called.add(res_name)
                if res_name in self.usages:
                    if self.usages[res_name].in_use < 0:
                        return {res_name: 2}
                    else:
                        return {res_name: self.usages[res_name].in_use - 1}
                return {res_name: 0}
            return sync

        self.resources = {}
        for res_name in ('instances', 'cores', 'ram'):
            res = quota.ReservableResource(res_name, make_sync(res_name))
            self.resources[res_name] = res

        self.expire = timeutils.utcnow() + datetime.timedelta(seconds=3600)

        self.usages = {}
        self.usages_created = {}
        self.reservations_created = {}

        def fake_get_session():
            return FakeSession()

        def fake_get_quota_usages(context, session):
            return self.usages.copy()

        def fake_quota_usage_create(context, project_id, resource, in_use,
                                    reserved, until_refresh, session=None,
                                    save=True):
            quota_usage_ref = self._make_quota_usage(
                project_id, resource, in_use, reserved, until_refresh,
                timeutils.utcnow(), timeutils.utcnow())

            self.usages_created[resource] = quota_usage_ref

            return quota_usage_ref

        def fake_reservation_create(context, uuid, usage_id, project_id,
                                    resource, delta, expire, session=None):
            reservation_ref = self._make_reservation(
                uuid, usage_id, project_id, resource, delta, expire,
                timeutils.utcnow(), timeutils.utcnow())

            self.reservations_created[resource] = reservation_ref

            return reservation_ref

        self.stubs.Set(sqa_api, 'get_session', fake_get_session)
        self.stubs.Set(sqa_api, '_get_quota_usages', fake_get_quota_usages)
        self.stubs.Set(sqa_api, '_quota_usage_create', fake_quota_usage_create)
        self.stubs.Set(sqa_api, 'reservation_create', fake_reservation_create)

        self.useFixture(test.TimeOverride())

    def _make_quota_usage(self, project_id, resource, in_use, reserved,
                          until_refresh, created_at, updated_at):
        quota_usage_ref = FakeUsage()
        quota_usage_ref.id = len(self.usages) + len(self.usages_created)
        quota_usage_ref.project_id = project_id
        quota_usage_ref.resource = resource
        quota_usage_ref.in_use = in_use
        quota_usage_ref.reserved = reserved
        quota_usage_ref.until_refresh = until_refresh
        quota_usage_ref.created_at = created_at
        quota_usage_ref.updated_at = updated_at
        quota_usage_ref.deleted_at = None
        quota_usage_ref.deleted = False

        return quota_usage_ref

    def init_usage(self, project_id, resource, in_use, reserved,
                   until_refresh=None, created_at=None, updated_at=None):
        if created_at is None:
            created_at = timeutils.utcnow()
        if updated_at is None:
            updated_at = timeutils.utcnow()

        quota_usage_ref = self._make_quota_usage(project_id, resource, in_use,
                                                 reserved, until_refresh,
                                                 created_at, updated_at)

        self.usages[resource] = quota_usage_ref

    def compare_usage(self, usage_dict, expected):
        for usage in expected:
            resource = usage['resource']
            for key, value in usage.items():
                actual = getattr(usage_dict[resource], key)
                self.assertEqual(actual, value,
                                 "%s != %s on usage for resource %s" %
                                 (actual, value, resource))

    def _make_reservation(self, uuid, usage_id, project_id, resource,
                          delta, expire, created_at, updated_at):
        reservation_ref = sqa_models.Reservation()
        reservation_ref.id = len(self.reservations_created)
        reservation_ref.uuid = uuid
        reservation_ref.usage_id = usage_id
        reservation_ref.project_id = project_id
        reservation_ref.resource = resource
        reservation_ref.delta = delta
        reservation_ref.expire = expire
        reservation_ref.created_at = created_at
        reservation_ref.updated_at = updated_at
        reservation_ref.deleted_at = None
        reservation_ref.deleted = False

        return reservation_ref

    def compare_reservation(self, reservations, expected):
        reservations = set(reservations)
        for resv in expected:
            resource = resv['resource']
            resv_obj = self.reservations_created[resource]

            self.assertIn(resv_obj.uuid, reservations)
            reservations.discard(resv_obj.uuid)

            for key, value in resv.items():
                actual = getattr(resv_obj, key)
                self.assertEqual(actual, value,
                                 "%s != %s on reservation for resource %s" %
                                 (actual, value, resource))

        self.assertEqual(len(reservations), 0)

    def test_quota_reserve_create_usages(self):
        context = FakeContext('test_project', 'test_class')
        quotas = dict(
            instances=5,
            cores=10,
            ram=10 * 1024,
            )
        deltas = dict(
            instances=2,
            cores=4,
            ram=2 * 1024,
            )
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 0, 0)

        self.assertEqual(self.sync_called, set(['instances', 'cores', 'ram']))
        self.compare_usage(self.usages_created, [
                dict(resource='instances',
                     project_id='test_project',
                     in_use=0,
                     reserved=2,
                     until_refresh=None),
                dict(resource='cores',
                     project_id='test_project',
                     in_use=0,
                     reserved=4,
                     until_refresh=None),
                dict(resource='ram',
                     project_id='test_project',
                     in_use=0,
                     reserved=2 * 1024,
                     until_refresh=None),
                ])
        self.compare_reservation(result, [
                dict(resource='instances',
                     usage_id=self.usages_created['instances'],
                     project_id='test_project',
                     delta=2),
                dict(resource='cores',
                     usage_id=self.usages_created['cores'],
                     project_id='test_project',
                     delta=4),
                dict(resource='ram',
                     usage_id=self.usages_created['ram'],
                     delta=2 * 1024),
                ])

    def test_quota_reserve_negative_in_use(self):
        self.init_usage('test_project', 'instances', -1, 0, until_refresh=1)
        self.init_usage('test_project', 'cores', -1, 0, until_refresh=1)
        self.init_usage('test_project', 'ram', -1, 0, until_refresh=1)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(
            instances=5,
            cores=10,
            ram=10 * 1024,
            )
        deltas = dict(
            instances=2,
            cores=4,
            ram=2 * 1024,
            )
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 5, 0)

        self.assertEqual(self.sync_called, set(['instances', 'cores', 'ram']))
        self.compare_usage(self.usages, [
                dict(resource='instances',
                     project_id='test_project',
                     in_use=2,
                     reserved=2,
                     until_refresh=5),
                dict(resource='cores',
                     project_id='test_project',
                     in_use=2,
                     reserved=4,
                     until_refresh=5),
                dict(resource='ram',
                     project_id='test_project',
                     in_use=2,
                     reserved=2 * 1024,
                     until_refresh=5),
                ])
        self.assertEqual(self.usages_created, {})
        self.compare_reservation(result, [
                dict(resource='instances',
                     usage_id=self.usages['instances'],
                     project_id='test_project',
                     delta=2),
                dict(resource='cores',
                     usage_id=self.usages['cores'],
                     project_id='test_project',
                     delta=4),
                dict(resource='ram',
                     usage_id=self.usages['ram'],
                     delta=2 * 1024),
                ])

    def test_quota_reserve_until_refresh(self):
        self.init_usage('test_project', 'instances', 3, 0, until_refresh=1)
        self.init_usage('test_project', 'cores', 3, 0, until_refresh=1)
        self.init_usage('test_project', 'ram', 3, 0, until_refresh=1)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(
            instances=5,
            cores=10,
            ram=10 * 1024,
            )
        deltas = dict(
            instances=2,
            cores=4,
            ram=2 * 1024,
            )
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 5, 0)

        self.assertEqual(self.sync_called, set(['instances', 'cores', 'ram']))
        self.compare_usage(self.usages, [
                dict(resource='instances',
                     project_id='test_project',
                     in_use=2,
                     reserved=2,
                     until_refresh=5),
                dict(resource='cores',
                     project_id='test_project',
                     in_use=2,
                     reserved=4,
                     until_refresh=5),
                dict(resource='ram',
                     project_id='test_project',
                     in_use=2,
                     reserved=2 * 1024,
                     until_refresh=5),
                ])
        self.assertEqual(self.usages_created, {})
        self.compare_reservation(result, [
                dict(resource='instances',
                     usage_id=self.usages['instances'],
                     project_id='test_project',
                     delta=2),
                dict(resource='cores',
                     usage_id=self.usages['cores'],
                     project_id='test_project',
                     delta=4),
                dict(resource='ram',
                     usage_id=self.usages['ram'],
                     delta=2 * 1024),
                ])

    def test_quota_reserve_max_age(self):
        max_age = 3600
        record_created = (timeutils.utcnow() -
                          datetime.timedelta(seconds=max_age))
        self.init_usage('test_project', 'instances', 3, 0,
                        created_at=record_created, updated_at=record_created)
        self.init_usage('test_project', 'cores', 3, 0,
                        created_at=record_created, updated_at=record_created)
        self.init_usage('test_project', 'ram', 3, 0,
                        created_at=record_created, updated_at=record_created)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(
            instances=5,
            cores=10,
            ram=10 * 1024,
            )
        deltas = dict(
            instances=2,
            cores=4,
            ram=2 * 1024,
            )
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 0, max_age)

        self.assertEqual(self.sync_called, set(['instances', 'cores', 'ram']))
        self.compare_usage(self.usages, [
                dict(resource='instances',
                     project_id='test_project',
                     in_use=2,
                     reserved=2,
                     until_refresh=None),
                dict(resource='cores',
                     project_id='test_project',
                     in_use=2,
                     reserved=4,
                     until_refresh=None),
                dict(resource='ram',
                     project_id='test_project',
                     in_use=2,
                     reserved=2 * 1024,
                     until_refresh=None),
                ])
        self.assertEqual(self.usages_created, {})
        self.compare_reservation(result, [
                dict(resource='instances',
                     usage_id=self.usages['instances'],
                     project_id='test_project',
                     delta=2),
                dict(resource='cores',
                     usage_id=self.usages['cores'],
                     project_id='test_project',
                     delta=4),
                dict(resource='ram',
                     usage_id=self.usages['ram'],
                     delta=2 * 1024),
                ])

    def test_quota_reserve_no_refresh(self):
        self.init_usage('test_project', 'instances', 3, 0)
        self.init_usage('test_project', 'cores', 3, 0)
        self.init_usage('test_project', 'ram', 3, 0)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(
            instances=5,
            cores=10,
            ram=10 * 1024,
            )
        deltas = dict(
            instances=2,
            cores=4,
            ram=2 * 1024,
            )
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 0, 0)

        self.assertEqual(self.sync_called, set([]))
        self.compare_usage(self.usages, [
                dict(resource='instances',
                     project_id='test_project',
                     in_use=3,
                     reserved=2,
                     until_refresh=None),
                dict(resource='cores',
                     project_id='test_project',
                     in_use=3,
                     reserved=4,
                     until_refresh=None),
                dict(resource='ram',
                     project_id='test_project',
                     in_use=3,
                     reserved=2 * 1024,
                     until_refresh=None),
                ])
        self.assertEqual(self.usages_created, {})
        self.compare_reservation(result, [
                dict(resource='instances',
                     usage_id=self.usages['instances'],
                     project_id='test_project',
                     delta=2),
                dict(resource='cores',
                     usage_id=self.usages['cores'],
                     project_id='test_project',
                     delta=4),
                dict(resource='ram',
                     usage_id=self.usages['ram'],
                     delta=2 * 1024),
                ])

    def test_quota_reserve_unders(self):
        self.init_usage('test_project', 'instances', 1, 0)
        self.init_usage('test_project', 'cores', 3, 0)
        self.init_usage('test_project', 'ram', 1 * 1024, 0)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(
            instances=5,
            cores=10,
            ram=10 * 1024,
            )
        deltas = dict(
            instances=-2,
            cores=-4,
            ram=-2 * 1024,
            )
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 0, 0)

        self.assertEqual(self.sync_called, set([]))
        self.compare_usage(self.usages, [
                dict(resource='instances',
                     project_id='test_project',
                     in_use=1,
                     reserved=0,
                     until_refresh=None),
                dict(resource='cores',
                     project_id='test_project',
                     in_use=3,
                     reserved=0,
                     until_refresh=None),
                dict(resource='ram',
                     project_id='test_project',
                     in_use=1 * 1024,
                     reserved=0,
                     until_refresh=None),
                ])
        self.assertEqual(self.usages_created, {})
        self.compare_reservation(result, [
                dict(resource='instances',
                     usage_id=self.usages['instances'],
                     project_id='test_project',
                     delta=-2),
                dict(resource='cores',
                     usage_id=self.usages['cores'],
                     project_id='test_project',
                     delta=-4),
                dict(resource='ram',
                     usage_id=self.usages['ram'],
                     delta=-2 * 1024),
                ])

    def test_quota_reserve_overs(self):
        self.init_usage('test_project', 'instances', 4, 0)
        self.init_usage('test_project', 'cores', 8, 0)
        self.init_usage('test_project', 'ram', 10 * 1024, 0)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(
            instances=5,
            cores=10,
            ram=10 * 1024,
            )
        deltas = dict(
            instances=2,
            cores=4,
            ram=2 * 1024,
            )
        self.assertRaises(exception.OverQuota,
                          sqa_api.quota_reserve,
                          context, self.resources, quotas,
                          deltas, self.expire, 0, 0)

        self.assertEqual(self.sync_called, set([]))
        self.compare_usage(self.usages, [
                dict(resource='instances',
                     project_id='test_project',
                     in_use=4,
                     reserved=0,
                     until_refresh=None),
                dict(resource='cores',
                     project_id='test_project',
                     in_use=8,
                     reserved=0,
                     until_refresh=None),
                dict(resource='ram',
                     project_id='test_project',
                     in_use=10 * 1024,
                     reserved=0,
                     until_refresh=None),
                ])
        self.assertEqual(self.usages_created, {})
        self.assertEqual(self.reservations_created, {})

    def test_quota_reserve_reduction(self):
        self.init_usage('test_project', 'instances', 10, 0)
        self.init_usage('test_project', 'cores', 20, 0)
        self.init_usage('test_project', 'ram', 20 * 1024, 0)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(
            instances=5,
            cores=10,
            ram=10 * 1024,
            )
        deltas = dict(
            instances=-2,
            cores=-4,
            ram=-2 * 1024,
            )
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 0, 0)

        self.assertEqual(self.sync_called, set([]))
        self.compare_usage(self.usages, [
                dict(resource='instances',
                     project_id='test_project',
                     in_use=10,
                     reserved=0,
                     until_refresh=None),
                dict(resource='cores',
                     project_id='test_project',
                     in_use=20,
                     reserved=0,
                     until_refresh=None),
                dict(resource='ram',
                     project_id='test_project',
                     in_use=20 * 1024,
                     reserved=0,
                     until_refresh=None),
                ])
        self.assertEqual(self.usages_created, {})
        self.compare_reservation(result, [
                dict(resource='instances',
                     usage_id=self.usages['instances'],
                     project_id='test_project',
                     delta=-2),
                dict(resource='cores',
                     usage_id=self.usages['cores'],
                     project_id='test_project',
                     delta=-4),
                dict(resource='ram',
                     usage_id=self.usages['ram'],
                     project_id='test_project',
                     delta=-2 * 1024),
                ])
