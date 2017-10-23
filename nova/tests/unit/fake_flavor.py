#    Copyright 2015 IBM Corp.
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

from nova import objects
from nova.objects import fields


def fake_db_flavor(**updates):
    db_flavor = {
        'id': 1,
        'name': 'fake_flavor',
        'memory_mb': 1024,
        'vcpus': 1,
        'root_gb': 100,
        'ephemeral_gb': 0,
        'flavorid': 'abc',
        'swap': 0,
        'disabled': False,
        'is_public': True,
        'extra_specs': {},
        'projects': [],
        'description': None
        }

    for name, field in objects.Flavor.fields.items():
        if name in db_flavor:
            continue
        if field.nullable:
            db_flavor[name] = None
        elif field.default != fields.UnspecifiedDefault:
            db_flavor[name] = field.default
        else:
            raise Exception('fake_db_flavor needs help with %s' % name)

    if updates:
        db_flavor.update(updates)

    return db_flavor


def fake_flavor_obj(context, **updates):
    expected_attrs = updates.pop('expected_attrs', None)
    return objects.Flavor._from_db_object(context,
               objects.Flavor(), fake_db_flavor(**updates),
               expected_attrs=expected_attrs)
