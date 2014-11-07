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
Tests For Loadable class handling.
"""

from nova import exception
from nova import test
from nova.tests.unit import fake_loadables


class LoadablesTestCase(test.NoDBTestCase):
    def setUp(self):
        super(LoadablesTestCase, self).setUp()
        self.fake_loader = fake_loadables.FakeLoader()
        # The name that we imported above for testing
        self.test_package = 'nova.tests.unit.fake_loadables'

    def test_loader_init(self):
        self.assertEqual(self.fake_loader.package, self.test_package)
        # Test the path of the module
        ending_path = '/' + self.test_package.replace('.', '/')
        self.assertTrue(self.fake_loader.path.endswith(ending_path))
        self.assertEqual(self.fake_loader.loadable_cls_type,
                         fake_loadables.FakeLoadable)

    def _compare_classes(self, classes, expected):
        class_names = [cls.__name__ for cls in classes]
        self.assertEqual(set(class_names), set(expected))

    def test_get_all_classes(self):
        classes = self.fake_loader.get_all_classes()
        expected_class_names = ['FakeLoadableSubClass1',
                                'FakeLoadableSubClass2',
                                'FakeLoadableSubClass5',
                                'FakeLoadableSubClass6']
        self._compare_classes(classes, expected_class_names)

    def test_get_matching_classes(self):
        prefix = self.test_package
        test_classes = [prefix + '.fake_loadable1.FakeLoadableSubClass1',
                        prefix + '.fake_loadable2.FakeLoadableSubClass5']
        classes = self.fake_loader.get_matching_classes(test_classes)
        expected_class_names = ['FakeLoadableSubClass1',
                                'FakeLoadableSubClass5']
        self._compare_classes(classes, expected_class_names)

    def test_get_matching_classes_with_underscore(self):
        prefix = self.test_package
        test_classes = [prefix + '.fake_loadable1.FakeLoadableSubClass1',
                        prefix + '.fake_loadable2._FakeLoadableSubClass7']
        self.assertRaises(exception.ClassNotFound,
                          self.fake_loader.get_matching_classes,
                          test_classes)

    def test_get_matching_classes_with_wrong_type1(self):
        prefix = self.test_package
        test_classes = [prefix + '.fake_loadable1.FakeLoadableSubClass4',
                        prefix + '.fake_loadable2.FakeLoadableSubClass5']
        self.assertRaises(exception.ClassNotFound,
                          self.fake_loader.get_matching_classes,
                          test_classes)

    def test_get_matching_classes_with_wrong_type2(self):
        prefix = self.test_package
        test_classes = [prefix + '.fake_loadable1.FakeLoadableSubClass1',
                        prefix + '.fake_loadable2.FakeLoadableSubClass8']
        self.assertRaises(exception.ClassNotFound,
                          self.fake_loader.get_matching_classes,
                          test_classes)

    def test_get_matching_classes_with_one_function(self):
        prefix = self.test_package
        test_classes = [prefix + '.fake_loadable1.return_valid_classes',
                        prefix + '.fake_loadable2.FakeLoadableSubClass5']
        classes = self.fake_loader.get_matching_classes(test_classes)
        expected_class_names = ['FakeLoadableSubClass1',
                                'FakeLoadableSubClass2',
                                'FakeLoadableSubClass5']
        self._compare_classes(classes, expected_class_names)

    def test_get_matching_classes_with_two_functions(self):
        prefix = self.test_package
        test_classes = [prefix + '.fake_loadable1.return_valid_classes',
                        prefix + '.fake_loadable2.return_valid_class']
        classes = self.fake_loader.get_matching_classes(test_classes)
        expected_class_names = ['FakeLoadableSubClass1',
                                'FakeLoadableSubClass2',
                                'FakeLoadableSubClass6']
        self._compare_classes(classes, expected_class_names)

    def test_get_matching_classes_with_function_including_invalids(self):
        # When using a method, no checking is done on valid classes.
        prefix = self.test_package
        test_classes = [prefix + '.fake_loadable1.return_invalid_classes',
                        prefix + '.fake_loadable2.return_valid_class']
        classes = self.fake_loader.get_matching_classes(test_classes)
        expected_class_names = ['FakeLoadableSubClass1',
                                '_FakeLoadableSubClass3',
                                'FakeLoadableSubClass4',
                                'FakeLoadableSubClass6']
        self._compare_classes(classes, expected_class_names)
