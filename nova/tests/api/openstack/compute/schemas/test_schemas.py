# Copyright 2012 OpenStack Foundation
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

import glob
import os

import lxml.etree

from nova import test

SCHEMAS = "nova/api/openstack/compute/schemas"


class RelaxNGSchemaTestCase(test.NoDBTestCase):
    """various validation tasks for the RelaxNG schemas

    lxml.etree has no built-in way to validate an entire namespace
    (i.e., multiple RelaxNG schema files defining elements in the same
    namespace), so we define a few tests that should hopefully reduce
    the risk of an inconsistent namespace
    """

    def _load_schema(self, schemafile):
        return lxml.etree.RelaxNG(lxml.etree.parse(schemafile))

    def _load_test_cases(self, path):
        """load test cases from the given path."""
        rv = dict(valid=[], invalid=[])
        path = os.path.join(os.path.dirname(__file__), path)
        for ctype in rv.keys():
            for cfile in glob.glob(os.path.join(path, ctype, "*.xml")):
                rv[ctype].append(lxml.etree.parse(cfile))
        return rv

    def _validate_schema(self, schemafile):
        """validate a single RelaxNG schema file."""
        try:
            self._load_schema(schemafile)
        except lxml.etree.RelaxNGParseError as err:
            self.fail("%s is not a valid RelaxNG schema: %s" %
                      (schemafile, err))

    def _api_versions(self):
        """get a list of API versions."""
        return [''] + [os.path.basename(v)
                       for v in glob.glob(os.path.join(SCHEMAS, "v*"))]

    def _schema_files(self, api_version):
        return glob.glob(os.path.join(SCHEMAS, api_version, "*.rng"))

    def test_schema_validity(self):
        for api_version in self._api_versions():
            for schema in self._schema_files(api_version):
                self._validate_schema(schema)

    def test_schema_duplicate_elements(self):
        for api_version in self._api_versions():
            elements = dict()
            duplicates = dict()
            for schemafile in self._schema_files(api_version):
                schema = lxml.etree.parse(schemafile)
                fname = os.path.basename(schemafile)
                if schema.getroot().tag != "element":
                    # we don't do any sort of validation on grammars
                    # yet
                    continue
                el_name = schema.getroot().get("name")
                if el_name in elements:
                    duplicates.setdefault(el_name,
                                          [elements[el_name]]).append(fname)
                else:
                    elements[el_name] = fname
            self.assertEqual(len(duplicates), 0,
                             "Duplicate element definitions found: %s" %
                             "; ".join("%s in %s" % dup
                                       for dup in duplicates.items()))

    def test_schema_explicit_cases(self):
        cases = {'v1.1/flavors.rng': self._load_test_cases("v1.1/flavors"),
                 'v1.1/images.rng': self._load_test_cases("v1.1/images"),
                 'v1.1/servers.rng': self._load_test_cases("v1.1/servers")}

        for schemafile, caselists in cases.items():
            schema = self._load_schema(os.path.join(SCHEMAS, schemafile))
            for case in caselists['valid']:
                self.assertTrue(schema.validate(case),
                                "Schema validation failed against %s: %s\n%s" %
                                (schemafile, schema.error_log, case))

            for case in caselists['invalid']:
                self.assertFalse(
                    schema.validate(case),
                    "Schema validation succeeded unexpectedly against %s: %s"
                    "\n%s" % (schemafile, schema.error_log, case))
