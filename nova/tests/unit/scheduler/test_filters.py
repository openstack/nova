# Copyright 2012 OpenStack Foundation  # All Rights Reserved.
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
"""
Tests For Scheduler Host Filters.
"""

import inspect
import sys

from nova import filters
from nova import loadables
from nova import test


class Filter1(filters.BaseFilter):
    """Test Filter class #1."""
    pass


class Filter2(filters.BaseFilter):
    """Test Filter class #2."""
    pass


class FiltersTestCase(test.NoDBTestCase):
    def test_filter_all(self):
        filter_obj_list = ['obj1', 'obj2', 'obj3']
        filter_properties = 'fake_filter_properties'
        base_filter = filters.BaseFilter()

        self.mox.StubOutWithMock(base_filter, '_filter_one')

        base_filter._filter_one('obj1', filter_properties).AndReturn(True)
        base_filter._filter_one('obj2', filter_properties).AndReturn(False)
        base_filter._filter_one('obj3', filter_properties).AndReturn(True)

        self.mox.ReplayAll()

        result = base_filter.filter_all(filter_obj_list, filter_properties)
        self.assertTrue(inspect.isgenerator(result))
        self.assertEqual(['obj1', 'obj3'], list(result))

    def test_filter_all_recursive_yields(self):
        # Test filter_all() allows generators from previous filter_all()s.
        # filter_all() yields results.  We want to make sure that we can
        # call filter_all() with generators returned from previous calls
        # to filter_all().
        filter_obj_list = ['obj1', 'obj2', 'obj3']
        filter_properties = 'fake_filter_properties'
        base_filter = filters.BaseFilter()

        self.mox.StubOutWithMock(base_filter, '_filter_one')

        total_iterations = 200

        # The order that _filter_one is going to get called gets
        # confusing because we will be recursively yielding things..
        # We are going to simulate the first call to filter_all()
        # returning False for 'obj2'.  So, 'obj1' will get yielded
        # 'total_iterations' number of times before the first filter_all()
        # call gets to processing 'obj2'.  We then return 'False' for it.
        # After that, 'obj3' gets yielded 'total_iterations' number of
        # times.
        for x in xrange(total_iterations):
            base_filter._filter_one('obj1', filter_properties).AndReturn(True)
        base_filter._filter_one('obj2', filter_properties).AndReturn(False)
        for x in xrange(total_iterations):
            base_filter._filter_one('obj3', filter_properties).AndReturn(True)
        self.mox.ReplayAll()

        objs = iter(filter_obj_list)
        for x in xrange(total_iterations):
            # Pass in generators returned from previous calls.
            objs = base_filter.filter_all(objs, filter_properties)
        self.assertTrue(inspect.isgenerator(objs))
        self.assertEqual(['obj1', 'obj3'], list(objs))

    def test_get_filtered_objects(self):
        filter_objs_initial = ['initial', 'filter1', 'objects1']
        filter_objs_second = ['second', 'filter2', 'objects2']
        filter_objs_last = ['last', 'filter3', 'objects3']
        filter_properties = 'fake_filter_properties'

        def _fake_base_loader_init(*args, **kwargs):
            pass

        self.stubs.Set(loadables.BaseLoader, '__init__',
                       _fake_base_loader_init)

        filt1_mock = self.mox.CreateMock(Filter1)
        filt2_mock = self.mox.CreateMock(Filter2)

        self.mox.StubOutWithMock(sys.modules[__name__], 'Filter1',
                                 use_mock_anything=True)
        self.mox.StubOutWithMock(filt1_mock, 'run_filter_for_index')
        self.mox.StubOutWithMock(filt1_mock, 'filter_all')
        self.mox.StubOutWithMock(sys.modules[__name__], 'Filter2',
                                 use_mock_anything=True)
        self.mox.StubOutWithMock(filt2_mock, 'run_filter_for_index')
        self.mox.StubOutWithMock(filt2_mock, 'filter_all')

        filt1_mock.run_filter_for_index(0).AndReturn(True)
        filt1_mock.filter_all(filter_objs_initial,
                              filter_properties).AndReturn(filter_objs_second)
        filt2_mock.run_filter_for_index(0).AndReturn(True)
        filt2_mock.filter_all(filter_objs_second,
                              filter_properties).AndReturn(filter_objs_last)

        self.mox.ReplayAll()

        filter_handler = filters.BaseFilterHandler(filters.BaseFilter)
        filter_mocks = [filt1_mock, filt2_mock]
        result = filter_handler.get_filtered_objects(filter_mocks,
                                                     filter_objs_initial,
                                                     filter_properties)
        self.assertEqual(filter_objs_last, result)

    def test_get_filtered_objects_for_index(self):
        """Test that we don't call a filter when its
        run_filter_for_index() method returns false
        """
        filter_objs_initial = ['initial', 'filter1', 'objects1']
        filter_objs_second = ['second', 'filter2', 'objects2']
        filter_properties = 'fake_filter_properties'

        def _fake_base_loader_init(*args, **kwargs):
            pass

        self.stubs.Set(loadables.BaseLoader, '__init__',
                       _fake_base_loader_init)

        filt1_mock = self.mox.CreateMock(Filter1)
        filt2_mock = self.mox.CreateMock(Filter2)

        self.mox.StubOutWithMock(sys.modules[__name__], 'Filter1',
                                 use_mock_anything=True)
        self.mox.StubOutWithMock(filt1_mock, 'run_filter_for_index')
        self.mox.StubOutWithMock(filt1_mock, 'filter_all')
        self.mox.StubOutWithMock(sys.modules[__name__], 'Filter2',
                                 use_mock_anything=True)
        self.mox.StubOutWithMock(filt2_mock, 'run_filter_for_index')
        self.mox.StubOutWithMock(filt2_mock, 'filter_all')

        filt1_mock.run_filter_for_index(0).AndReturn(True)
        filt1_mock.filter_all(filter_objs_initial,
                              filter_properties).AndReturn(filter_objs_second)
        # return false so filter_all will not be called
        filt2_mock.run_filter_for_index(0).AndReturn(False)

        self.mox.ReplayAll()

        filter_handler = filters.BaseFilterHandler(filters.BaseFilter)
        filter_mocks = [filt1_mock, filt2_mock]
        filter_handler.get_filtered_objects(filter_mocks,
                                            filter_objs_initial,
                                            filter_properties)

    def test_get_filtered_objects_none_response(self):
        filter_objs_initial = ['initial', 'filter1', 'objects1']
        filter_properties = 'fake_filter_properties'

        def _fake_base_loader_init(*args, **kwargs):
            pass

        self.stubs.Set(loadables.BaseLoader, '__init__',
                       _fake_base_loader_init)

        filt1_mock = self.mox.CreateMock(Filter1)
        filt2_mock = self.mox.CreateMock(Filter2)

        self.mox.StubOutWithMock(sys.modules[__name__], 'Filter1',
                                 use_mock_anything=True)
        self.mox.StubOutWithMock(filt1_mock, 'run_filter_for_index')
        self.mox.StubOutWithMock(filt1_mock, 'filter_all')
        # Shouldn't be called.
        self.mox.StubOutWithMock(sys.modules[__name__], 'Filter2',
                                 use_mock_anything=True)
        self.mox.StubOutWithMock(filt2_mock, 'filter_all')

        filt1_mock.run_filter_for_index(0).AndReturn(True)
        filt1_mock.filter_all(filter_objs_initial,
                              filter_properties).AndReturn(None)
        self.mox.ReplayAll()

        filter_handler = filters.BaseFilterHandler(filters.BaseFilter)
        filter_mocks = [filt1_mock, filt2_mock]
        result = filter_handler.get_filtered_objects(filter_mocks,
                                                     filter_objs_initial,
                                                     filter_properties)
        self.assertIsNone(result)
