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

from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import instance_list
from nova import context
from nova.db import api as db
from nova import exception
from nova import objects
from nova import test


class InstanceListTestCase(test.TestCase):
    NUMBER_OF_CELLS = 3

    def setUp(self):
        super(InstanceListTestCase, self).setUp()

        self.context = context.RequestContext('fake', 'fake')
        self.num_instances = 3
        self.instances = []

        start = datetime.datetime(1985, 10, 25, 1, 21, 0)
        dt = start
        spread = datetime.timedelta(minutes=10)

        self.cells = objects.CellMappingList.get_all(self.context)
        # Create three instances in each of the real cells. Leave the
        # first cell empty to make sure we don't break with an empty
        # one.
        for cell in self.cells[1:]:
            for i in range(0, self.num_instances):
                with context.target_cell(self.context, cell) as cctx:
                    inst = objects.Instance(
                        context=cctx,
                        project_id=self.context.project_id,
                        user_id=self.context.user_id,
                        created_at=start,
                        launched_at=dt,
                        instance_type_id=i,
                        hostname='%s-inst%i' % (cell.name, i))
                    inst.create()
                    if i % 2 == 0:
                        # Make some faults for this instance
                        for n in range(0, i + 1):
                            msg = 'fault%i-%s' % (n, inst.hostname)
                            f = objects.InstanceFault(context=cctx,
                                                      instance_uuid=inst.uuid,
                                                      code=i,
                                                      message=msg,
                                                      details='fake',
                                                      host='fakehost')
                            f.create()

                self.instances.append(inst)
                im = objects.InstanceMapping(context=self.context,
                                             project_id=inst.project_id,
                                             user_id=inst.user_id,
                                             instance_uuid=inst.uuid,
                                             cell_mapping=cell)
                im.create()
                dt += spread

    def test_get_sorted(self):
        filters = {}
        limit = None
        marker = None
        columns = []
        sort_keys = ['uuid']
        sort_dirs = ['asc']
        obj, insts = instance_list.get_instances_sorted(self.context, filters,
                                                        limit, marker, columns,
                                                        sort_keys, sort_dirs)
        uuids = [inst['uuid'] for inst in insts]
        self.assertEqual(sorted(uuids), uuids)
        self.assertEqual(len(self.instances), len(uuids))

    def test_get_sorted_descending(self):
        filters = {}
        limit = None
        marker = None
        columns = []
        sort_keys = ['uuid']
        sort_dirs = ['desc']
        obj, insts = instance_list.get_instances_sorted(self.context, filters,
                                                        limit, marker, columns,
                                                        sort_keys, sort_dirs)
        uuids = [inst['uuid'] for inst in insts]
        self.assertEqual(list(reversed(sorted(uuids))), uuids)
        self.assertEqual(len(self.instances), len(uuids))

    def test_get_sorted_with_filter(self):
        filters = {'instance_type_id': 1}
        limit = None
        marker = None
        columns = []
        sort_keys = ['uuid']
        sort_dirs = ['asc']
        obj, insts = instance_list.get_instances_sorted(self.context, filters,
                                                        limit, marker, columns,
                                                        sort_keys, sort_dirs)
        uuids = [inst['uuid'] for inst in insts]
        expected = [inst['uuid'] for inst in self.instances
                    if inst['instance_type_id'] == 1]
        self.assertEqual(list(sorted(expected)), uuids)

    def test_get_sorted_by_defaults(self):
        filters = {}
        limit = None
        marker = None
        columns = []
        sort_keys = None
        sort_dirs = None
        obj, insts = instance_list.get_instances_sorted(self.context, filters,
                                                        limit, marker, columns,
                                                        sort_keys, sort_dirs)
        uuids = set([inst['uuid'] for inst in insts])
        expected = set([inst['uuid'] for inst in self.instances])
        self.assertEqual(expected, uuids)

    def test_get_sorted_with_limit(self):
        obj, insts = instance_list.get_instances_sorted(self.context, {},
                                                        5, None,
                                                        [], ['uuid'], ['asc'])
        uuids = [inst['uuid'] for inst in insts]
        had_uuids = [inst.uuid for inst in self.instances]
        self.assertEqual(sorted(had_uuids)[:5], uuids)
        self.assertEqual(5, len(uuids))

    def test_get_sorted_with_large_limit(self):
        obj, insts = instance_list.get_instances_sorted(self.context, {},
                                                        5000, None,
                                                        [], ['uuid'], ['asc'])
        uuids = [inst['uuid'] for inst in insts]
        self.assertEqual(sorted(uuids), uuids)
        self.assertEqual(len(self.instances), len(uuids))

    def test_get_sorted_with_large_limit_batched(self):
        obj, insts = instance_list.get_instances_sorted(self.context, {},
                                                        5000, None,
                                                        [], ['uuid'], ['asc'],
                                                        batch_size=2)
        uuids = [inst['uuid'] for inst in insts]
        self.assertEqual(sorted(uuids), uuids)
        self.assertEqual(len(self.instances), len(uuids))

    def _test_get_sorted_with_limit_marker(self, sort_by, pages=2, pagesize=2,
                                           sort_dir='asc'):
        """Get multiple pages by a sort key and validate the results.

        This requests $pages of $pagesize, followed by a final page with
        no limit, and a final-final page which should be empty. It validates
        that we got a consistent set of results no patter where the page
        boundary is, that we got all the results after the unlimited query,
        and that the final page comes back empty when we use the last
        instance as a marker.
        """
        insts = []

        page = 0
        while True:
            if page >= pages:
                # We've requested the specified number of limited (by pagesize)
                # pages, so request a penultimate page with no limit which
                # should always finish out the result.
                limit = None
            else:
                # Request a limited-size page for the first $pages pages.
                limit = pagesize

            if insts:
                # If we're not on the first page, use the last instance we
                # received as the marker
                marker = insts[-1]['uuid']
            else:
                # No marker for the first page
                marker = None

            batch = list(
                instance_list.get_instances_sorted(self.context, {},
                                                   limit, marker,
                                                   [], [sort_by],
                                                   [sort_dir])[1])
            if not batch:
                # This should only happen when we've pulled the last empty
                # page because we used the marker of the last instance. If
                # we end up with a non-deterministic ordering, we'd loop
                # forever.
                break
            insts.extend(batch)
            page += 1
            if page > len(self.instances) * 2:
                # Do this sanity check in case we introduce (or find) another
                # repeating page bug like #1721791. Without this we loop
                # until timeout, which is less obvious.
                raise Exception('Infinite paging loop')

        # We should have requested exactly (or one more unlimited) pages
        self.assertIn(page, (pages, pages + 1))

        # Make sure the full set matches what we know to be true
        found = [x[sort_by] for x in insts]
        had = [x[sort_by] for x in self.instances]

        if sort_by in ('launched_at', 'created_at'):
            # We're comparing objects and database entries, so we need to
            # squash the tzinfo of the object ones so we can compare
            had = [x.replace(tzinfo=None) for x in had]

        self.assertEqual(len(had), len(found))
        if sort_dir == 'asc':
            self.assertEqual(sorted(had), found)
        else:
            self.assertEqual(list(reversed(sorted(had))), found)

    def test_get_sorted_with_limit_marker_stable(self):
        """Test sorted by hostname.

        This will be a stable sort that won't change on each run.
        """
        self._test_get_sorted_with_limit_marker(sort_by='hostname')

    def test_get_sorted_with_limit_marker_stable_reverse(self):
        """Test sorted by hostname.

        This will be a stable sort that won't change on each run.
        """
        self._test_get_sorted_with_limit_marker(sort_by='hostname',
                                                sort_dir='desc')

    def test_get_sorted_with_limit_marker_stable_different_pages(self):
        """Test sorted by hostname with different page sizes.

        Just do the above with page seams in different places.
        """
        self._test_get_sorted_with_limit_marker(sort_by='hostname',
                                                pages=3, pagesize=1)

    def test_get_sorted_with_limit_marker_stable_different_pages_reverse(self):
        """Test sorted by hostname with different page sizes.

        Just do the above with page seams in different places.
        """
        self._test_get_sorted_with_limit_marker(sort_by='hostname',
                                                pages=3, pagesize=1,
                                                sort_dir='desc')

    def test_get_sorted_with_limit_marker_random(self):
        """Test sorted by uuid.

        This will not be stable and the actual ordering will depend on
        uuid generation and thus be different on each run. Do this in
        addition to the stable sort above to keep us honest.
        """
        self._test_get_sorted_with_limit_marker(sort_by='uuid')

    def test_get_sorted_with_limit_marker_random_different_pages(self):
        """Test sorted by uuid with different page sizes.

        Just do the above with page seams in different places.
        """
        self._test_get_sorted_with_limit_marker(sort_by='uuid',
                                                pages=3, pagesize=2)

    def test_get_sorted_with_limit_marker_datetime(self):
        """Test sorted by launched_at.

        This tests that we can do all of this, but with datetime
        fields.
        """
        self._test_get_sorted_with_limit_marker(sort_by='launched_at')

    def test_get_sorted_with_limit_marker_datetime_same(self):
        """Test sorted by created_at.

        This tests that we can do all of this, but with datetime
        fields that are identical.
        """
        self._test_get_sorted_with_limit_marker(sort_by='created_at')

    def test_get_sorted_with_deleted_marker(self):
        marker = self.instances[1]['uuid']

        before = list(
            instance_list.get_instances_sorted(self.context, {},
                                               None, marker,
                                               [], None, None)[1])

        db.instance_destroy(self.context, marker)

        after = list(
            instance_list.get_instances_sorted(self.context, {},
                                               None, marker,
                                               [], None, None)[1])

        self.assertEqual(before, after)

    def test_get_sorted_with_invalid_marker(self):
        self.assertRaises(exception.MarkerNotFound,
                          list, instance_list.get_instances_sorted(
                              self.context, {}, None, 'not-a-marker',
                              [], None, None)[1])

    def test_get_sorted_with_purged_instance(self):
        """Test that we handle a mapped but purged instance."""
        im = objects.InstanceMapping(self.context,
                                     instance_uuid=uuids.missing,
                                     project_id=self.context.project_id,
                                     user_id=self.context.user_id,
                                     cell=self.cells[0])
        im.create()
        self.assertRaises(exception.MarkerNotFound,
                          list, instance_list.get_instances_sorted(
                              self.context, {}, None, uuids.missing,
                              [], None, None)[1])

    def _test_get_paginated_with_filter(self, filters):

        found_uuids = []
        marker = None
        while True:
            # Query for those instances, sorted by a different key in
            # pages of one until we've consumed them all
            batch = list(
                instance_list.get_instances_sorted(self.context,
                                                   filters,
                                                   1, marker, [],
                                                   ['hostname'],
                                                   ['asc'])[1])
            if not batch:
                break
            found_uuids.extend([x['uuid'] for x in batch])
            marker = found_uuids[-1]

        return found_uuids

    def test_get_paginated_with_uuid_filter(self):
        """Test getting pages with uuid filters.

        This runs through the results of a uuid-filtered query in pages of
        length one to ensure that we land on markers that are filtered out
        of the query and are not accidentally returned.
        """
        # Pick a set of the instances by uuid, when sorted by uuid
        all_uuids = [x['uuid'] for x in self.instances]
        filters = {'uuid': sorted(all_uuids)[:7]}

        found_uuids = self._test_get_paginated_with_filter(filters)

        # Make sure we found all (and only) the instances we asked for
        self.assertEqual(set(found_uuids), set(filters['uuid']))
        self.assertEqual(7, len(found_uuids))

    def test_get_paginated_with_other_filter(self):
        """Test getting pages with another filter.

        This runs through the results of a filtered query in pages of
        length one to ensure we land on markers that are filtered out
        of the query and are not accidentally returned.
        """
        expected = [inst['uuid'] for inst in self.instances
                    if inst['instance_type_id'] == 1]
        filters = {'instance_type_id': 1}

        found_uuids = self._test_get_paginated_with_filter(filters)

        self.assertEqual(set(expected), set(found_uuids))

    def test_get_paginated_with_uuid_and_other_filter(self):
        """Test getting pages with a uuid and other type of filter.

        We do this to make sure that we still find (but exclude) the
        marker even if one of the other filters would have included
        it.
        """
        # Pick a set of the instances by uuid, when sorted by uuid
        all_uuids = [x['uuid'] for x in self.instances]
        filters = {'uuid': sorted(all_uuids)[:7],
                   'user_id': 'fake'}

        found_uuids = self._test_get_paginated_with_filter(filters)

        # Make sure we found all (and only) the instances we asked for
        self.assertEqual(set(found_uuids), set(filters['uuid']))
        self.assertEqual(7, len(found_uuids))

    def test_get_sorted_with_faults(self):
        """Make sure we get faults when we ask for them."""
        insts = list(
            instance_list.get_instances_sorted(self.context, {},
                                               None, None,
                                               ['fault'],
                                               ['hostname'], ['asc'])[1])

        # Two of the instances in each cell have faults (0th and 2nd)
        expected_faults = self.NUMBER_OF_CELLS * 2
        expected_no_fault = len(self.instances) - expected_faults
        faults = [inst['fault'] for inst in insts]
        self.assertEqual(expected_no_fault, faults.count(None))

    def test_get_sorted_paginated_with_faults(self):
        """Get pages of one with faults.

        Do this specifically so we make sure we land on faulted marker
        instances to ensure we don't omit theirs.
        """
        insts = []
        while True:
            if insts:
                marker = insts[-1]['uuid']
            else:
                marker = None
            batch = list(
                instance_list.get_instances_sorted(self.context, {},
                                                   1, marker,
                                                   ['fault'],
                                                   ['hostname'], ['asc'])[1])
            if not batch:
                break
            insts.extend(batch)

        self.assertEqual(len(self.instances), len(insts))
        # Two of the instances in each cell have faults (0th and 2nd)
        expected_faults = self.NUMBER_OF_CELLS * 2
        expected_no_fault = len(self.instances) - expected_faults
        faults = [inst['fault'] for inst in insts]
        self.assertEqual(expected_no_fault, faults.count(None))

    def test_instance_list_minimal_cells(self):
        """Get a list of instances with a subset of cell mappings."""
        last_cell = self.cells[-1]
        with context.target_cell(self.context, last_cell) as cctxt:
            last_cell_instances = db.instance_get_all(cctxt)
            last_cell_uuids = [inst['uuid'] for inst in last_cell_instances]

        instances = list(
            instance_list.get_instances_sorted(self.context, {},
                                               None, None, [],
                                               ['uuid'], ['asc'],
                                               cell_mappings=self.cells[:-1])
                                               [1])
        found_uuids = [inst['hostname'] for inst in instances]
        had_uuids = [inst['hostname'] for inst in self.instances
                     if inst['uuid'] not in last_cell_uuids]
        self.assertEqual(sorted(had_uuids), sorted(found_uuids))


class TestInstanceListObjects(test.TestCase):
    def setUp(self):
        super(TestInstanceListObjects, self).setUp()

        self.context = context.RequestContext('fake', 'fake')
        self.num_instances = 3
        self.instances = []

        start = datetime.datetime(1985, 10, 25, 1, 21, 0)
        dt = start
        spread = datetime.timedelta(minutes=10)

        cells = objects.CellMappingList.get_all(self.context)
        # Create three instances in each of the real cells. Leave the
        # first cell empty to make sure we don't break with an empty
        # one
        for cell in cells[1:]:
            for i in range(0, self.num_instances):
                with context.target_cell(self.context, cell) as cctx:
                    inst = objects.Instance(
                        context=cctx,
                        project_id=self.context.project_id,
                        user_id=self.context.user_id,
                        created_at=start,
                        launched_at=dt,
                        instance_type_id=i,
                        hostname='%s-inst%i' % (cell.name, i))
                    inst.create()
                    if i % 2 == 0:
                        # Make some faults for this instance
                        for n in range(0, i + 1):
                            msg = 'fault%i-%s' % (n, inst.hostname)
                            f = objects.InstanceFault(context=cctx,
                                                      instance_uuid=inst.uuid,
                                                      code=i,
                                                      message=msg,
                                                      details='fake',
                                                      host='fakehost')
                            f.create()

                self.instances.append(inst)
                im = objects.InstanceMapping(context=self.context,
                                             project_id=inst.project_id,
                                             user_id=inst.user_id,
                                             instance_uuid=inst.uuid,
                                             cell_mapping=cell)
                im.create()
                dt += spread

    def test_get_instance_objects_sorted(self):
        filters = {}
        limit = None
        marker = None
        expected_attrs = []
        sort_keys = ['uuid']
        sort_dirs = ['asc']
        insts, down_cell_uuids = instance_list.get_instance_objects_sorted(
            self.context, filters, limit, marker, expected_attrs,
            sort_keys, sort_dirs)
        found_uuids = [x.uuid for x in insts]
        had_uuids = sorted([x['uuid'] for x in self.instances])
        self.assertEqual(had_uuids, found_uuids)

        # Make sure none of the instances have fault set
        self.assertEqual(0, len([inst for inst in insts
                                 if 'fault' in inst]))

    def test_get_instance_objects_sorted_with_fault(self):
        filters = {}
        limit = None
        marker = None
        expected_attrs = ['fault']
        sort_keys = ['uuid']
        sort_dirs = ['asc']
        insts, down_cell_uuids = instance_list.get_instance_objects_sorted(
            self.context, filters, limit, marker, expected_attrs,
            sort_keys, sort_dirs)
        found_uuids = [x.uuid for x in insts]
        had_uuids = sorted([x['uuid'] for x in self.instances])
        self.assertEqual(had_uuids, found_uuids)

        # They should all have fault set, but only some have
        # actual faults
        self.assertEqual(2, len([inst for inst in insts
                                 if inst.fault]))

    def test_get_instance_objects_sorted_paged(self):
        """Query a full first page and ensure an empty second one.

        This uses created_at which is enforced to be the same across
        each instance by setUp(). This will help make sure we still
        have a stable ordering, even when we only claim to care about
        created_at.
        """
        instp1, down_cell_uuids = instance_list.get_instance_objects_sorted(
            self.context, {}, None, None, [],
            ['created_at'], ['asc'])
        self.assertEqual(len(self.instances), len(instp1))
        instp2, down_cell_uuids = instance_list.get_instance_objects_sorted(
            self.context, {}, None, instp1[-1]['uuid'], [],
            ['created_at'], ['asc'])
        self.assertEqual(0, len(instp2))
