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

# nova.image.glance._translate_from_glance() returns datetime
# objects, not strings.
NOW_DATE = datetime.datetime(2010, 10, 11, 10, 30, 22)


def get_image_fixtures():
    """Returns a set of image fixture dicts for use in unit tests.

    Returns a set of dicts representing images/snapshots of varying statuses
    that would be returned from a call to
    `glanceclient.client.Client.images.list`. The IDs of the images returned
    start at 123 and go to 131, with the following brief summary of image
    attributes:

    |      ID          Type            Status          Notes
    |      ----------------------------------------------------------
    |      123         Public image    active
    |      124         Snapshot        queued
    |      125         Snapshot        saving
    |      126         Snapshot        active
    |      127         Snapshot        killed
    |      128         Snapshot        deleted
    |      129         Snapshot        pending_delete
    |      130         Public image    active          Has no name

    """

    image_id = 123

    fixtures = []

    def add_fixture(**kwargs):
        kwargs.update(created_at=NOW_DATE,
                      updated_at=NOW_DATE)
        fixtures.append(kwargs)

    # Public image
    add_fixture(id=str(image_id), name='public image', is_public=True,
                status='active', properties={'key1': 'value1'},
                min_ram="128", min_disk="10", size='25165824')
    image_id += 1

    # Snapshot for User 1
    uuid = 'aa640691-d1a7-4a67-9d3c-d35ee6b3cc74'
    snapshot_properties = {'instance_uuid': uuid, 'user_id': 'fake'}
    for status in ('queued', 'saving', 'active', 'killed',
                   'deleted', 'pending_delete'):
        deleted = False if status != 'deleted' else True
        deleted_at = NOW_DATE if deleted else None

        add_fixture(id=str(image_id), name='%s snapshot' % status,
                    is_public=False, status=status,
                    properties=snapshot_properties, size='25165824',
                    deleted=deleted, deleted_at=deleted_at)
        image_id += 1

    # Image without a name
    add_fixture(id=str(image_id), is_public=True, status='active',
                properties={})
    # Image for permission tests
    image_id += 1
    add_fixture(id=str(image_id), is_public=True, status='active',
                properties={}, owner='authorized_fake')

    return fixtures
