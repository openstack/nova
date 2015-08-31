#    Copyright 2015 Red Hat, Inc.
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
from oslo_utils import uuidutils

from nova import context
from nova import objects
from nova.objects import base
from nova.tests.unit.objects import test_objects


class _TestRequestSpecObject(object):

    def test_image_meta_from_image_as_object(self):
        # Just isolating the test for the from_dict() method
        image_meta = objects.ImageMeta(name='foo')

        spec = objects.RequestSpec()
        spec._image_meta_from_image(image_meta)
        self.assertEqual(image_meta, spec.image)

    @mock.patch.object(objects.ImageMeta, 'from_dict')
    def test_image_meta_from_image_as_dict(self, from_dict):
        # Just isolating the test for the from_dict() method
        image_meta = objects.ImageMeta(name='foo')
        from_dict.return_value = image_meta

        spec = objects.RequestSpec()
        spec._image_meta_from_image({'name': 'foo'})
        self.assertEqual(image_meta, spec.image)

    def test_image_meta_from_image_as_none(self):
        # just add a dumb check to have a full coverage
        spec = objects.RequestSpec()
        spec._image_meta_from_image(None)
        self.assertIsNone(spec.image)

    @mock.patch.object(base, 'obj_to_primitive')
    def test_to_legacy_image(self, obj_to_primitive):
        spec = objects.RequestSpec(image=objects.ImageMeta())
        fake_dict = mock.Mock()
        obj_to_primitive.return_value = fake_dict

        self.assertEqual(fake_dict, spec._to_legacy_image())
        obj_to_primitive.assert_called_once_with(spec.image)

    @mock.patch.object(base, 'obj_to_primitive')
    def test_to_legacy_image_with_none(self, obj_to_primitive):
        spec = objects.RequestSpec(image=None)

        self.assertEqual({}, spec._to_legacy_image())
        self.assertFalse(obj_to_primitive.called)

    def test_from_instance_as_object(self):
        instance = objects.Instance()
        instance.uuid = uuidutils.generate_uuid()
        instance.numa_topology = None
        instance.pci_requests = None
        instance.project_id = '1'
        instance.availability_zone = 'nova'

        spec = objects.RequestSpec()
        spec._from_instance(instance)
        instance_fields = ['numa_topology', 'pci_requests', 'uuid',
                           'project_id', 'availability_zone']
        for field in instance_fields:
            if field == 'uuid':
                self.assertEqual(getattr(instance, field),
                                 getattr(spec, 'instance_uuid'))
            else:
                self.assertEqual(getattr(instance, field),
                                 getattr(spec, field))

    def test_from_instance_as_dict(self):
        instance = dict(uuid=uuidutils.generate_uuid(),
                        numa_topology=None,
                        pci_requests=None,
                        project_id='1',
                        availability_zone='nova')

        spec = objects.RequestSpec()
        spec._from_instance(instance)
        instance_fields = ['numa_topology', 'pci_requests', 'uuid',
                           'project_id', 'availability_zone']
        for field in instance_fields:
            if field == 'uuid':
                self.assertEqual(instance.get(field),
                                 getattr(spec, 'instance_uuid'))
            else:
                self.assertEqual(instance.get(field), getattr(spec, field))

    def test_from_flavor_as_object(self):
        flavor = objects.Flavor()

        spec = objects.RequestSpec()
        spec._from_flavor(flavor)
        self.assertEqual(flavor, spec.flavor)

    def test_from_flavor_as_dict(self):
        flavor_dict = dict(id=1)
        ctxt = context.RequestContext('fake', 'fake')
        spec = objects.RequestSpec(ctxt)

        spec._from_flavor(flavor_dict)
        self.assertIsInstance(spec.flavor, objects.Flavor)
        self.assertEqual({'id': 1}, spec.flavor.obj_get_changes())

    def test_to_legacy_instance(self):
        spec = objects.RequestSpec()
        spec.flavor = objects.Flavor(root_gb=10,
                                     ephemeral_gb=0,
                                     memory_mb=10,
                                     vcpus=1)
        spec.numa_topology = None
        spec.pci_requests = None
        spec.project_id = '1'
        spec.availability_zone = 'nova'

        instance = spec._to_legacy_instance()
        self.assertEqual({'root_gb': 10,
                          'ephemeral_gb': 0,
                          'memory_mb': 10,
                          'vcpus': 1,
                          'numa_topology': None,
                          'pci_requests': None,
                          'project_id': '1',
                          'availability_zone': 'nova'}, instance)

    def test_to_legacy_instance_with_unset_values(self):
        spec = objects.RequestSpec()
        self.assertEqual({}, spec._to_legacy_instance())

    def test_from_retry(self):
        retry_dict = {'num_attempts': 1,
                      'hosts': [['fake1', 'node1']]}
        ctxt = context.RequestContext('fake', 'fake')
        spec = objects.RequestSpec(ctxt)
        spec._from_retry(retry_dict)
        self.assertIsInstance(spec.retry, objects.SchedulerRetries)
        self.assertEqual(1, spec.retry.num_attempts)
        self.assertIsInstance(spec.retry.hosts, objects.ComputeNodeList)
        self.assertEqual(1, len(spec.retry.hosts))
        self.assertEqual('fake1', spec.retry.hosts[0].host)
        self.assertEqual('node1', spec.retry.hosts[0].hypervisor_hostname)

    def test_from_retry_missing_values(self):
        retry_dict = {}
        ctxt = context.RequestContext('fake', 'fake')
        spec = objects.RequestSpec(ctxt)
        spec._from_retry(retry_dict)
        self.assertIsNone(spec.retry)

    def test_populate_group_info(self):
        filt_props = {}
        filt_props['group_updated'] = True
        filt_props['group_policies'] = set(['affinity'])
        filt_props['group_hosts'] = set(['fake1'])

        spec = objects.RequestSpec()
        spec._populate_group_info(filt_props)
        self.assertIsInstance(spec.instance_group, objects.InstanceGroup)
        self.assertEqual(['affinity'], spec.instance_group.policies)
        self.assertEqual(['fake1'], spec.instance_group.hosts)

    def test_populate_group_info_missing_values(self):
        filt_props = {}
        spec = objects.RequestSpec()
        spec._populate_group_info(filt_props)
        self.assertIsNone(spec.instance_group)

    def test_from_limits(self):
        limits_dict = {'numa_topology': None,
                       'vcpu': 1.0,
                       'disk_gb': 1.0,
                       'memory_mb': 1.0}
        spec = objects.RequestSpec()
        spec._from_limits(limits_dict)
        self.assertIsInstance(spec.limits, objects.SchedulerLimits)
        self.assertIsNone(spec.limits.numa_topology)
        self.assertEqual(1, spec.limits.vcpu)
        self.assertEqual(1, spec.limits.disk_gb)
        self.assertEqual(1, spec.limits.memory_mb)

    def test_from_limits_missing_values(self):
        limits_dict = {}
        spec = objects.RequestSpec()
        spec._from_limits(limits_dict)
        self.assertIsInstance(spec.limits, objects.SchedulerLimits)
        self.assertIsNone(spec.limits.numa_topology)
        self.assertIsNone(spec.limits.vcpu)
        self.assertIsNone(spec.limits.disk_gb)
        self.assertIsNone(spec.limits.memory_mb)

    def test_from_hints(self):
        hints_dict = {'foo_str': '1',
                      'bar_list': ['2']}
        spec = objects.RequestSpec()
        spec._from_hints(hints_dict)
        expected = {'foo_str': ['1'],
                    'bar_list': ['2']}
        self.assertEqual(expected, spec.scheduler_hints)

    def test_from_hints_with_no_hints(self):
        spec = objects.RequestSpec()
        spec._from_hints(None)
        self.assertIsNone(spec.scheduler_hints)

    @mock.patch.object(objects.SchedulerLimits, 'from_dict')
    def test_from_primitives(self, mock_limits):
        spec_dict = {'instance_type': objects.Flavor(),
                     'instance_properties': objects.Instance(
                         uuid=uuidutils.generate_uuid(),
                         numa_topology=None,
                         pci_requests=None,
                         project_id=1,
                         availability_zone='nova')}
        filt_props = {}

        # We seriously don't care about the return values, we just want to make
        # sure that all the fields are set
        mock_limits.return_value = None

        ctxt = context.RequestContext('fake', 'fake')
        spec = objects.RequestSpec.from_primitives(ctxt, spec_dict, filt_props)
        mock_limits.assert_called_once_with({})
        # Make sure that all fields are set using that helper method
        for field in [f for f in spec.obj_fields if f != 'id']:
            self.assertEqual(True, spec.obj_attr_is_set(field),
                             'Field: %s is not set' % field)
        # just making sure that the context is set by the method
        self.assertEqual(ctxt, spec._context)

    def test_get_scheduler_hint(self):
        spec_obj = objects.RequestSpec(scheduler_hints={'foo_single': ['1'],
                                                        'foo_mul': ['1', '2']})
        self.assertEqual('1', spec_obj.get_scheduler_hint('foo_single'))
        self.assertEqual(['1', '2'], spec_obj.get_scheduler_hint('foo_mul'))
        self.assertIsNone(spec_obj.get_scheduler_hint('oops'))
        self.assertEqual('bar', spec_obj.get_scheduler_hint('oops',
                                                            default='bar'))

    def test_get_scheduler_hint_with_no_hints(self):
        spec_obj = objects.RequestSpec()
        self.assertEqual('bar', spec_obj.get_scheduler_hint('oops',
                                                            default='bar'))

    @mock.patch.object(objects.RequestSpec, '_to_legacy_instance')
    @mock.patch.object(base, 'obj_to_primitive')
    def test_to_legacy_request_spec_dict(self, image_to_primitive,
                                         spec_to_legacy_instance):
        fake_image_dict = mock.Mock()
        image_to_primitive.return_value = fake_image_dict
        fake_instance = {'root_gb': 1.0,
                         'ephemeral_gb': 1.0,
                         'memory_mb': 1.0,
                         'vcpus': 1,
                         'numa_topology': None,
                         'pci_requests': None,
                         'project_id': '1',
                         'availability_zone': 'nova',
                         'uuid': '1'}
        spec_to_legacy_instance.return_value = fake_instance

        fake_flavor = objects.Flavor(root_gb=10,
                                     ephemeral_gb=0,
                                     memory_mb=512,
                                     vcpus=1)
        spec = objects.RequestSpec(num_instances=1,
                                   image=objects.ImageMeta(),
                                   # instance properties
                                   numa_topology=None,
                                   pci_requests=None,
                                   project_id=1,
                                   availability_zone='nova',
                                   instance_uuid='1',
                                   flavor=fake_flavor)
        spec_dict = spec.to_legacy_request_spec_dict()
        expected = {'num_instances': 1,
                    'image': fake_image_dict,
                    'instance_properties': fake_instance,
                    'instance_type': fake_flavor}
        self.assertEqual(expected, spec_dict)

    def test_to_legacy_request_spec_dict_with_unset_values(self):
        spec = objects.RequestSpec()
        self.assertEqual({'num_instances': 1,
                          'image': {},
                          'instance_properties': {},
                          'instance_type': {}},
                         spec.to_legacy_request_spec_dict())

    def test_to_legacy_filter_properties_dict(self):
        fake_numa_limits = objects.NUMATopologyLimits()
        fake_computes_obj = objects.ComputeNodeList(
            objects=[objects.ComputeNode(host='fake1',
                                         hypervisor_hostname='node1')])
        spec = objects.RequestSpec(
            ignore_hosts=['ignoredhost'],
            force_hosts=['fakehost'],
            force_nodes=['fakenode'],
            retry=objects.SchedulerRetries(num_attempts=1,
                                           hosts=fake_computes_obj),
            limits=objects.SchedulerLimits(numa_topology=fake_numa_limits,
                                           vcpu=1.0,
                                           disk_gb=10.0,
                                           memory_mb=8192.0),
            instance_group=objects.InstanceGroup(hosts=['fake1'],
                                                 policies=['affinity']),
            scheduler_hints={'foo': ['bar']})
        expected = {'ignore_hosts': ['ignoredhost'],
                    'force_hosts': ['fakehost'],
                    'force_nodes': ['fakenode'],
                    'retry': {'num_attempts': 1,
                              'hosts': [['fake1', 'node1']]},
                    'limits': {'numa_topology': fake_numa_limits,
                               'vcpu': 1.0,
                               'disk_gb': 10.0,
                               'memory_mb': 8192.0},
                    'group_updated': True,
                    'group_hosts': set(['fake1']),
                    'group_policies': set(['affinity']),
                    'scheduler_hints': {'foo': 'bar'}}
        self.assertEqual(expected, spec.to_legacy_filter_properties_dict())

    def test_to_legacy_filter_properties_dict_with_nullable_values(self):
        spec = objects.RequestSpec(force_hosts=None,
                                   force_nodes=None,
                                   retry=None,
                                   limits=None,
                                   instance_group=None,
                                   scheduler_hints=None)
        self.assertEqual({}, spec.to_legacy_filter_properties_dict())

    def test_to_legacy_filter_properties_dict_with_unset_values(self):
        spec = objects.RequestSpec()
        self.assertEqual({}, spec.to_legacy_filter_properties_dict())


class TestRequestSpecObject(test_objects._LocalTest,
                            _TestRequestSpecObject):
    pass


class TestRemoteRequestSpecObject(test_objects._RemoteTest,
                                  _TestRequestSpecObject):
    pass
