# Copyright 2017 Huawei Technologies Co.,LTD.
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

from nova import exception
from nova import objects
from nova.tests.functional.regressions import test_bug_1670627


class TestDeleteFromCell0CheckQuotaRollback(
        test_bug_1670627.TestDeleteFromCell0CheckQuota):
    """This tests a regression introduced in the Ocata release.

    The _delete_while_booting method in the compute API was added in Ocata
    and will commit quota reservations for a usage decrement *before*
    attempting to destroy the instance. This is wrong since we should only
    adjust quota usage until *after* the instance is destroyed.

    If we fail to destroy the instance, then we rollback the quota reservation
    for the usage decrement.

    Because of how the Quotas object's commit and rollback methods work, they
    mask the fact that if you have already committed the reservation, a later
    attempt to rollback is a noop, which hid this regression.

    This test class extends the same regression test class for bug 1670627
    because the same regression from _delete_while_booting was copied into
    _delete which was added as part of fixing bug 1670627.

    For the regression, we can recreate it by attempting to delete an
    instance but stub out instance.destroy() to make it fail and then check
    quota usage which should be unchanged from before the delete request when
    the bug is fixed.
    """

    def test_delete_error_instance_in_cell0_and_check_quota(self):
        # Get the current quota usage
        starting_usage = self.api.get_limits()

        # Create the server which we expect to go into ERROR state.
        server = dict(
            name='cell0-quota-test',
            imageRef=self.image_id,
            flavorRef=self.flavor_id)
        server = self.api.post_server({'server': server})
        self.addCleanup(self._delete_server, server)
        self._wait_for_instance_status(server['id'], 'ERROR')

        # Check quota to see we've incremented usage by 1.
        current_usage = self.api.get_limits()
        self.assertEqual(starting_usage['absolute']['totalInstancesUsed'] + 1,
                         current_usage['absolute']['totalInstancesUsed'])

        # Now we stub out instance.destroy to fail with InstanceNotFound
        # which triggers the quotas.rollback call.
        original_instance_destroy = objects.Instance.destroy

        def fake_instance_destroy(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id=server['id'])
        self.stub_out('nova.objects.instance.Instance.destroy',
                      fake_instance_destroy)

        # Now delete the server and wait for it to be gone.
        self._delete_server(server)

        # Reset the stub so we can actually delete the instance on tearDown.
        self.stub_out('nova.objects.instance.Instance.destroy',
                      original_instance_destroy)

        # Now check the quota again. We should be back to the pre-delete usage.
        ending_usage = self.api.get_limits()
        self.assertEqual(current_usage['absolute']['totalInstancesUsed'],
                         ending_usage['absolute']['totalInstancesUsed'])
