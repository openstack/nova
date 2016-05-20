# Copyright 2013 Red Hat Inc.
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

import uuid

from oslo_utils import timeutils

from nova import block_device
from nova import objects


def fake_bdm_object(context, bdm_dict):
    """Creates a BlockDeviceMapping object from the given bdm_dict

    :param context: nova request context
    :param bdm_dict: dict of block device mapping info
    :returns: nova.objects.block_device.BlockDeviceMapping
    """
    # FakeDbBlockDeviceDict mutates the bdm_dict so make a copy of it.
    return objects.BlockDeviceMapping._from_db_object(
        context, objects.BlockDeviceMapping(),
        FakeDbBlockDeviceDict(bdm_dict.copy()))


class FakeDbBlockDeviceDict(block_device.BlockDeviceDict):
    """Defaults db fields - useful for mocking database calls."""

    def __init__(self, bdm_dict=None, anon=False, **kwargs):
        bdm_dict = bdm_dict or {}
        db_id = bdm_dict.pop('id', 1)
        instance_uuid = bdm_dict.pop('instance_uuid', str(uuid.uuid4()))

        super(FakeDbBlockDeviceDict, self).__init__(bdm_dict=bdm_dict,
                                                    **kwargs)
        fake_db_fields = {'instance_uuid': instance_uuid,
                          'deleted_at': None,
                          'deleted': 0}
        if not anon:
            fake_db_fields['id'] = db_id
            fake_db_fields['created_at'] = timeutils.utcnow()
            fake_db_fields['updated_at'] = timeutils.utcnow()
        self.update(fake_db_fields)


def AnonFakeDbBlockDeviceDict(bdm_dict, **kwargs):
    return FakeDbBlockDeviceDict(bdm_dict=bdm_dict, anon=True, **kwargs)
