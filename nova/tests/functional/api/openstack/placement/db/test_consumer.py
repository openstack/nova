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
from nova.db.sqlalchemy import api as db_api
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
        u = user_obj.User(self.ctx, external_id='fake-user')
        u.create()
        p = project_obj.Project(self.ctx, external_id='fake-project')
        p.create()
        c = consumer_obj.Consumer(
            self.ctx, uuid=uuids.consumer, user=u, project=p)
        c.create()
        c = consumer_obj.Consumer.get_by_uuid(self.ctx, uuids.consumer)
        self.assertEqual(1, c.id)
        self.assertEqual(1, c.project.id)
        self.assertEqual(1, c.user.id)
        self.assertRaises(exception.ConsumerExists, c.create)


class CreateIncompleteConsumersTestCase(tb.PlacementDbBaseTestCase):
    @db_api.api_context_manager.writer
    def _create_incomplete_allocations(self, ctx):
        # Create some allocations with consumers that don't exist in the
        # consumers table to represent old allocations that we expect to be
        # "cleaned up" with consumers table records that point to the sentinel
        # project/user records.
        c1_missing_uuid = uuids.c1_missing
        c2_missing_uuid = uuids.c2_missing
        ins_stmt = ALLOC_TBL.insert().values(
            resource_provider_id=1, resource_class_id=0,
            consumer_id=c1_missing_uuid, used=1)
        ctx.session.execute(ins_stmt)
        ins_stmt = ALLOC_TBL.insert().values(
            resource_provider_id=1, resource_class_id=0,
            consumer_id=c2_missing_uuid, used=1)
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
        alloc_to_consumer = sa.outerjoin(
            ALLOC_TBL, CONSUMER_TBL,
            ALLOC_TBL.c.consumer_id == CONSUMER_TBL.c.uuid)
        sel = sa.select([ALLOC_TBL])
        sel = sel.select_from(alloc_to_consumer)
        sel = sel.where(CONSUMER_TBL.c.id.is_(None))
        res = ctx.session.execute(sel).fetchall()
        self.assertEqual(0, len(res))

    def test_create_incomplete_consumers(self):
        """Test the online data migration that creates incomplete consumer
        records along with the incomplete consumer project/user records.
        """
        self._create_incomplete_allocations(self.ctx)
        res = consumer_obj.create_incomplete_consumers(self.ctx, 10)
        self.assertEqual((2, 2), res)
        self._check_incomplete_consumers(self.ctx)
        res = consumer_obj.create_incomplete_consumers(self.ctx, 10)
        self.assertEqual((0, 0), res)
