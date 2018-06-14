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

from oslo_config import cfg
import sqlalchemy as sa

from nova.api.openstack.placement import exception
from nova.api.openstack.placement.objects import consumer as consumer_obj
from nova.api.openstack.placement.objects import project as project_obj
from nova.api.openstack.placement.objects import resource_provider as rp_obj
from nova.api.openstack.placement.objects import user as user_obj
from nova import context
from nova.db.sqlalchemy import api as db_api
from nova import test
from nova.tests import fixtures
from nova.tests.functional.api.openstack.placement.db import test_base as tb
from nova.tests import uuidsentinel as uuids

CONF = cfg.CONF
CONSUMER_TBL = consumer_obj.CONSUMER_TBL
PROJECT_TBL = project_obj.PROJECT_TBL
USER_TBL = user_obj.USER_TBL
ALLOC_TBL = rp_obj._ALLOC_TBL


class ConsumerTestCase(tb.PlacementDbBaseTestCase):
    def test_non_existing_consumer(self):
        self.assertRaises(exception.ConsumerNotFound,
            consumer_obj.Consumer.get_by_uuid, self.ctx,
            uuids.non_existing_consumer)

    def test_create_and_get(self):
        u = user_obj.User(self.ctx, external_id='another-user')
        u.create()
        p = project_obj.Project(self.ctx, external_id='another-project')
        p.create()
        c = consumer_obj.Consumer(
            self.ctx, uuid=uuids.consumer, user=u, project=p)
        c.create()
        c = consumer_obj.Consumer.get_by_uuid(self.ctx, uuids.consumer)
        self.assertEqual(1, c.id)
        # Project ID == 1 is fake-project created in setup
        self.assertEqual(2, c.project.id)
        # User ID == 1 is fake-user created in setup
        self.assertEqual(2, c.user.id)
        self.assertRaises(exception.ConsumerExists, c.create)


@db_api.api_context_manager.reader
def _get_allocs_with_no_consumer_relationship(ctx):
    alloc_to_consumer = sa.outerjoin(
        ALLOC_TBL, CONSUMER_TBL,
        ALLOC_TBL.c.consumer_id == CONSUMER_TBL.c.uuid)
    sel = sa.select([ALLOC_TBL.c.consumer_id])
    sel = sel.select_from(alloc_to_consumer)
    sel = sel.where(CONSUMER_TBL.c.id.is_(None))
    return ctx.session.execute(sel).fetchall()


# NOTE(jaypipes): The tb.PlacementDbBaseTestCase creates a project and user
# which is why we don't base off that. We want a completely bare DB for this
# test.
class CreateIncompleteConsumersTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(CreateIncompleteConsumersTestCase, self).setUp()
        self.useFixture(fixtures.Database())
        self.api_db = self.useFixture(fixtures.Database(database='api'))
        self.ctx = context.RequestContext('fake-user', 'fake-project')

    @db_api.api_context_manager.writer
    def _create_incomplete_allocations(self, ctx):
        # Create some allocations with consumers that don't exist in the
        # consumers table to represent old allocations that we expect to be
        # "cleaned up" with consumers table records that point to the sentinel
        # project/user records.
        c1_missing_uuid = uuids.c1_missing
        c2_missing_uuid = uuids.c2_missing
        c3_missing_uuid = uuids.c3_missing
        for c_uuid in (c1_missing_uuid, c2_missing_uuid, c3_missing_uuid):
            ins_stmt = ALLOC_TBL.insert().values(
                resource_provider_id=1, resource_class_id=0,
                consumer_id=c_uuid, used=1)
            ctx.session.execute(ins_stmt)
        # Verify there are no records in the projects/users table
        project_count = ctx.session.scalar(
            sa.select([sa.func.count('*')]).select_from(PROJECT_TBL))
        self.assertEqual(0, project_count)
        user_count = ctx.session.scalar(
            sa.select([sa.func.count('*')]).select_from(USER_TBL))
        self.assertEqual(0, user_count)
        # Verify there are no consumer records for the missing consumers
        sel = CONSUMER_TBL.select(
            CONSUMER_TBL.c.uuid.in_([c1_missing_uuid, c2_missing_uuid]))
        res = ctx.session.execute(sel).fetchall()
        self.assertEqual(0, len(res))

    @db_api.api_context_manager.reader
    def _check_incomplete_consumers(self, ctx):
        incomplete_external_id = CONF.placement.incomplete_consumer_project_id

        # Verify we have a record in projects for the missing sentinel
        sel = PROJECT_TBL.select(
            PROJECT_TBL.c.external_id == incomplete_external_id)
        rec = ctx.session.execute(sel).first()
        self.assertEqual(incomplete_external_id, rec['external_id'])
        incomplete_proj_id = rec['id']

        # Verify we have a record in users for the missing sentinel
        sel = user_obj.USER_TBL.select(
            USER_TBL.c.external_id == incomplete_external_id)
        rec = ctx.session.execute(sel).first()
        self.assertEqual(incomplete_external_id, rec['external_id'])
        incomplete_user_id = rec['id']

        # Verify there are records in the consumers table for our old
        # allocation records created in the pre-migration setup and that the
        # projects and users referenced in those consumer records point to the
        # incomplete project/user
        sel = CONSUMER_TBL.select(CONSUMER_TBL.c.uuid == uuids.c1_missing)
        missing_c1 = ctx.session.execute(sel).first()
        self.assertEqual(incomplete_proj_id, missing_c1['project_id'])
        self.assertEqual(incomplete_user_id, missing_c1['user_id'])
        sel = CONSUMER_TBL.select(CONSUMER_TBL.c.uuid == uuids.c2_missing)
        missing_c2 = ctx.session.execute(sel).first()
        self.assertEqual(incomplete_proj_id, missing_c2['project_id'])
        self.assertEqual(incomplete_user_id, missing_c2['user_id'])

        # Ensure there are no more allocations with incomplete consumers
        res = _get_allocs_with_no_consumer_relationship(ctx)
        self.assertEqual(0, len(res))

    def test_create_incomplete_consumers(self):
        """Test the online data migration that creates incomplete consumer
        records along with the incomplete consumer project/user records.
        """
        self._create_incomplete_allocations(self.ctx)
        # We do a "really online" online data migration for incomplete
        # consumers when calling AllocationList.get_all_by_consumer_id() and
        # AllocationList.get_all_by_resource_provider() and there are still
        # incomplete consumer records. So, to simulate a situation where the
        # operator has yet to run the nova-manage online_data_migration CLI
        # tool completely, we first call
        # consumer_obj.create_incomplete_consumers() with a batch size of 1.
        # This should mean there will be two allocation records still remaining
        # with a missing consumer record (since we create 3 total to begin
        # with). We then query the allocations table directly to grab that
        # consumer UUID in the allocations table that doesn't refer to a
        # consumer table record and call
        # AllocationList.get_all_by_consumer_id() with that consumer UUID. This
        # should create the remaining missing consumer record "inline" in the
        # AllocationList.get_all_by_consumer_id() method.
        # After that happens, there should still be a single allocation record
        # that is missing a relation to the consumers table. We call the
        # AllocationList.get_all_by_resource_provider() method and verify that
        # method cleans up the remaining incomplete consumers relationship.
        res = consumer_obj.create_incomplete_consumers(self.ctx, 1)
        self.assertEqual((1, 1), res)

        # Grab the consumer UUID for the allocation record with a
        # still-incomplete consumer record.
        res = _get_allocs_with_no_consumer_relationship(self.ctx)
        self.assertEqual(2, len(res))
        still_missing = res[0][0]
        rp_obj.AllocationList.get_all_by_consumer_id(self.ctx, still_missing)

        # There should still be a single missing consumer relationship. Let's
        # grab that and call AllocationList.get_all_by_resource_provider()
        # which should clean that last one up for us.
        res = _get_allocs_with_no_consumer_relationship(self.ctx)
        self.assertEqual(1, len(res))
        still_missing = res[0][0]
        rp1 = rp_obj.ResourceProvider(self.ctx, id=1)
        rp_obj.AllocationList.get_all_by_resource_provider(self.ctx, rp1)

        # get_all_by_resource_provider() should have auto-completed the still
        # missing consumer record and _check_incomplete_consumers() should
        # assert correctly that there are no more incomplete consumer records.
        self._check_incomplete_consumers(self.ctx)
        res = consumer_obj.create_incomplete_consumers(self.ctx, 10)
        self.assertEqual((0, 0), res)
