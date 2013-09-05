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

from nova import db
from nova.objects import base
from nova.objects import utils as obj_utils


class InstanceFault(base.NovaPersistentObject, base.NovaObject):
    fields = {
        'id': int,
        'instance_uuid': str,
        'code': int,
        'message': obj_utils.str_or_none,
        'details': obj_utils.str_or_none,
        'host': obj_utils.str_or_none,
        }

    @staticmethod
    def _from_db_object(fault, db_fault):
        # NOTE(danms): These are identical right now
        for key in fault.fields:
            fault[key] = db_fault[key]
        fault.obj_reset_changes()
        return fault

    @base.remotable_classmethod
    def get_latest_for_instance(cls, context, instance_uuid):
        db_faults = db.instance_fault_get_by_instance_uuids(context,
                                                            [instance_uuid])
        if instance_uuid in db_faults and db_faults[instance_uuid]:
            return cls._from_db_object(cls(), db_faults[instance_uuid][0])


def _make_fault_list(faultlist, db_faultlist):
    faultlist.objects = []
    for instance_uuid in db_faultlist:
        for db_fault in db_faultlist[instance_uuid]:
            faultlist.objects.append(InstanceFault._from_db_object(
                InstanceFault(), db_fault))
    faultlist.obj_reset_changes()
    return faultlist


class InstanceFaultList(base.ObjectListBase, base.NovaObject):
    @base.remotable_classmethod
    def get_by_instance_uuids(cls, context, instance_uuids):
        db_faults = db.instance_fault_get_by_instance_uuids(context,
                                                            instance_uuids)
        return _make_fault_list(cls(), db_faults)
