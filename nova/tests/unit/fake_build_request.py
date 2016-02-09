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

from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova.network import model as network_model
from nova import objects
from nova.objects import fields
from nova.tests.unit import fake_request_spec


def _req_spec_to_db_format(req_spec):
    db_spec = {'spec': jsonutils.dumps(req_spec.obj_to_primitive()),
               'id': req_spec.id,
               'instance_uuid': req_spec.instance_uuid,
               }
    return db_spec


def fake_db_req(**updates):
    instance_uuid = uuidutils.generate_uuid()
    info_cache = objects.InstanceInfoCache()
    info_cache.instance_uuid = instance_uuid
    info_cache.network_info = network_model.NetworkInfo()
    req_spec = fake_request_spec.fake_spec_obj(
            context.RequestContext('fake-user', 'fake-project'))
    req_spec.id = 42
    req_spec.obj_reset_changes()
    db_build_request = {
            'id': 1,
            'project_id': 'fake-project',
            'user_id': 'fake-user',
            'display_name': '',
            'instance_metadata': jsonutils.dumps({'foo': 'bar'}),
            'progress': 0,
            'vm_state': vm_states.BUILDING,
            'task_state': task_states.SCHEDULING,
            'image_ref': None,
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': '::1',
            'info_cache': jsonutils.dumps(info_cache.obj_to_primitive()),
            'security_groups': jsonutils.dumps(
                objects.SecurityGroupList().obj_to_primitive()),
            'config_drive': False,
            'key_name': None,
            'locked_by': None,
            'request_spec': _req_spec_to_db_format(req_spec),
            'created_at': datetime.datetime(2016, 1, 16),
            'updated_at': datetime.datetime(2016, 1, 16),
    }

    for name, field in objects.BuildRequest.fields.items():
        if name in db_build_request:
            continue
        if field.nullable:
            db_build_request[name] = None
        elif field.default != fields.UnspecifiedDefault:
            db_build_request[name] = field.default
        else:
            raise Exception('fake_db_req needs help with %s' % name)

    if updates:
        db_build_request.update(updates)

    return db_build_request


def fake_req_obj(context, db_req=None):
    if db_req is None:
        db_req = fake_db_req()
    req_obj = objects.BuildRequest(context)
    for field in req_obj.fields:
        value = db_req[field]
        # create() can't be called if this is set
        if field == 'id':
            continue
        if isinstance(req_obj.fields[field], fields.ObjectField):
            value = value
            if field == 'request_spec':
                req_spec = objects.RequestSpec._from_db_object(context,
                        objects.RequestSpec(), value)
                req_obj.request_spec = req_spec
            elif field == 'info_cache':
                setattr(req_obj, field,
                        objects.InstanceInfoCache.obj_from_primitive(
                            jsonutils.loads(value)))
            elif field == 'security_groups':
                setattr(req_obj, field,
                        objects.SecurityGroupList.obj_from_primitive(
                            jsonutils.loads(value)))
        elif field == 'instance_metadata':
            setattr(req_obj, field, jsonutils.loads(value))
        else:
            setattr(req_obj, field, value)
    # This should never be a changed field
    req_obj.obj_reset_changes(['id'])
    return req_obj
