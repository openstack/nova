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
import uuid

from nova.objects import instance as instance_obj


def fake_db_secgroups(instance, names):
    secgroups = []
    for i, name in enumerate(names):
        secgroups.append(
            {'id': i,
             'instance_uuid': instance['uuid'],
             'name': 'secgroup-%i' % i,
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
    db_instance = {
        'id': 1,
        'deleted': False,
        'uuid': str(uuid.uuid4()),
        'user_id': 'fake-user',
        'project_id': 'fake-project',
        'host': 'fake-host',
        'created_at': datetime.datetime(1955, 11, 5),
        }
    for field, typefn in instance_obj.Instance.fields.items():
        if field in db_instance:
            continue
        try:
            db_instance[field] = typefn(None)
        except TypeError:
            db_instance[field] = typefn()

    if updates:
        db_instance.update(updates)

    if db_instance.get('security_groups'):
        db_instance['security_groups'] = fake_db_secgroups(
            db_instance, db_instance['security_groups'])

    return db_instance
