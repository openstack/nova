# Copyright 2019, Red Hat, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import collections

import mock

from nova.compute import task_states
from nova.compute import vm_states
from nova import objects
from nova import test
from nova.tests.functional import integrated_helpers


class TestDelete(integrated_helpers.ProviderUsageBaseTestCase):
    compute_driver = 'fake.MediumFakeDriver'

    def test_delete_during_create(self):
        compute = self._start_compute('compute1')

        def delete_race(instance):
            self.api.delete_server(instance.uuid)
            self._wait_for_server_parameter(
                {'id': instance.uuid},
                {'OS-EXT-STS:task_state': task_states.DELETING},
            )

        orig_save = objects.Instance.save

        # an in-memory record of the current instance task state as persisted
        # to the db.
        db_task_states = collections.defaultdict(str)
        active_after_deleting_error = [False]

        # A wrapper round instance.save() which allows us to inject a race
        # under specific conditions before calling the original instance.save()
        def wrap_save(instance, *wrap_args, **wrap_kwargs):
            # We're looking to inject the race before:
            #   instance.save(expected_task_state=task_states.SPAWNING)
            # towards the end of _build_and_run_instance.
            #
            # At this point the driver has finished creating the instance, but
            # we're still on the compute host and still holding the compute
            # host instance lock.
            #
            # This is just a convenient interception point. In order to race
            # the delete could have happened at any point prior to this since
            # the previous instance.save()
            expected_task_state = wrap_kwargs.get('expected_task_state')
            if (
                expected_task_state == task_states.SPAWNING
            ):
                delete_race(instance)

            orig_save(instance, *wrap_args, **wrap_kwargs)

            if (
                db_task_states[instance.uuid] == task_states.DELETING and
                instance.vm_state == vm_states.ACTIVE and
                instance.task_state is None
            ):
                # the instance was in the DELETING task state in the db, and we
                # overwrote that to set it to ACTIVE with no task state.
                # Bug 1848666.
                active_after_deleting_error[0] = True

            db_task_states[instance.uuid] = instance.task_state

        with test.nested(
            mock.patch('nova.objects.Instance.save', wrap_save),
            mock.patch.object(compute.driver, 'spawn'),
            mock.patch.object(compute.driver, 'unplug_vifs'),
        ) as (_, mock_spawn, mock_unplug_vifs):
            # the compute manager doesn't set the ERROR state in cleanup since
            # it might race with delete, therefore we'll be left in BUILDING
            server_req = self._build_server(networks='none')
            created_server = self.api.post_server({'server': server_req})
            self._wait_until_deleted(created_server)

            # assert that we spawned the instance, and unplugged vifs on
            # cleanup
            mock_spawn.assert_called()
            mock_unplug_vifs.assert_called()
            # FIXME(mdbooth): Bug 1848666
            self.assertTrue(active_after_deleting_error[0])
