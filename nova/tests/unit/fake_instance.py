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

import datetime

from oslo_serialization import jsonutils
from oslo_utils import uuidutils

from nova import objects
from nova.objects import fields


def fake_db_secgroups(instance, names):
    secgroups = []
    for i, name in enumerate(names):
        group_name = 'secgroup-%i' % i
        if isinstance(name, dict) and name.get('name'):
            group_name = name.get('name')
        secgroups.append(
            {'id': i,
             'instance_uuid': instance['uuid'],
             'name': group_name,
             'description': 'Fake secgroup',
             'user_id': instance['user_id'],
             'project_id': instance['project_id'],
             'deleted': False,
             'deleted_at': None,
             'created_at': None,
             'updated_at': None,
             })
    return secgroups


def fake_db_instance(**updates):
    if 'instance_type' in updates:
        if isinstance(updates['instance_type'], objects.Flavor):
            flavor = updates['instance_type']
        else:
            flavor = objects.Flavor(**updates['instance_type'])
        flavorinfo = jsonutils.dumps({
            'cur': flavor.obj_to_primitive(),
            'old': None,
            'new': None,
        })
    else:
        flavorinfo = None
    db_instance = {
        'id': 1,
        'deleted': False,
        'uuid': uuidutils.generate_uuid(),
        'user_id': 'fake-user',
        'project_id': 'fake-project',
        'host': 'fake-host',
        'created_at': datetime.datetime(1955, 11, 5),
        'pci_devices': [],
        'security_groups': [],
        'metadata': {},
        'system_metadata': {},
        'root_gb': 0,
        'ephemeral_gb': 0,
        'extra': {'pci_requests': None,
                  'flavor': flavorinfo,
                  'numa_topology': None,
                  'vcpu_model': None,
                  'device_metadata': None,
                  'trusted_certs': None,
                  'resources': None,
                 },
        'tags': [],
        'services': []
        }

    for name, field in objects.Instance.fields.items():
        if name in db_instance:
            continue
        if field.nullable:
            db_instance[name] = None
        elif field.default != fields.UnspecifiedDefault:
            db_instance[name] = field.default
        elif name in ['flavor', 'ec2_ids', 'keypairs']:
            pass
        else:
            raise Exception('fake_db_instance needs help with %s' % name)

    if updates:
        db_instance.update(updates)

    if db_instance.get('security_groups'):
        db_instance['security_groups'] = fake_db_secgroups(
            db_instance, db_instance['security_groups'])

    return db_instance


def fake_instance_obj(context, obj_instance_class=None, **updates):
    if obj_instance_class is None:
        obj_instance_class = objects.Instance
    expected_attrs = updates.pop('expected_attrs', None)
    flavor = updates.pop('flavor', None)
    if not flavor:
        flavor = objects.Flavor(id=1, name='flavor1',
                                memory_mb=256, vcpus=1,
                                root_gb=1, ephemeral_gb=1,
                                flavorid='1',
                                swap=0, rxtx_factor=1.0,
                                vcpu_weight=1,
                                disabled=False,
                                is_public=True,
                                extra_specs={},
                                projects=[])
    inst = obj_instance_class._from_db_object(context,
               obj_instance_class(), fake_db_instance(**updates),
               expected_attrs=expected_attrs)
    inst.keypairs = objects.KeyPairList(objects=[])
    inst.tags = objects.TagList()
    if flavor:
        inst.flavor = flavor
        # This is needed for instance quota counting until we have the
        # ability to count allocations in placement.
        if 'vcpus' in flavor and 'vcpus' not in updates:
            inst.vcpus = flavor.vcpus
        if 'memory_mb' in flavor and 'memory_mb' not in updates:
            inst.memory_mb = flavor.memory_mb
        if ('instance_type_id' not in inst or
                inst.instance_type_id is None and
                'id' in flavor):
            inst.instance_type_id = flavor.id
    inst.old_flavor = None
    inst.new_flavor = None
    inst.resources = None
    inst.migration_context = None
    inst.obj_reset_changes(recursive=True)
    return inst


def fake_fault_obj(context, instance_uuid, code=404,
                   message='HTTPNotFound',
                   details='Stock details for test',
                   **updates):
    fault = {
        'id': 1,
        'instance_uuid': instance_uuid,
        'code': code,
        'message': message,
        'details': details,
        'host': 'fake_host',
        'deleted': False,
        'created_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
        'updated_at': None,
        'deleted_at': None
    }
    if updates:
        fault.update(updates)
    return objects.InstanceFault._from_db_object(context,
                                                 objects.InstanceFault(),
                                                 fault)
