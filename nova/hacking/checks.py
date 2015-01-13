# Copyright (c) 2012, Cloudscaling
# All Rights Reserved.
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

import ast
import re

import pep8

"""
Guidelines for writing new hacking checks

 - Use only for Nova specific tests. OpenStack general tests
   should be submitted to the common 'hacking' module.
 - Pick numbers in the range N3xx. Find the current test with
   the highest allocated number and then pick the next value.
 - Keep the test method code in the source file ordered based
   on the N3xx value.
 - List the new rule in the top level HACKING.rst file
 - Add test cases for each new rule to nova/tests/test_hacking.py

"""

UNDERSCORE_IMPORT_FILES = []

session_check = re.compile(r"\w*def [a-zA-Z0-9].*[(].*session.*[)]")
cfg_re = re.compile(r".*\scfg\.")
vi_header_re = re.compile(r"^#\s+vim?:.+")
virt_file_re = re.compile(r"\./nova/(?:tests/)?virt/(\w+)/")
virt_import_re = re.compile(
    r"^\s*(?:import|from) nova\.(?:tests\.)?virt\.(\w+)")
virt_config_re = re.compile(
    r"CONF\.import_opt\('.*?', 'nova\.virt\.(\w+)('|.)")
author_tag_re = (re.compile("^\s*#\s*@?(a|A)uthor:"),
                 re.compile("^\.\.\s+moduleauthor::"))
asse_trueinst_re = re.compile(
                     r"(.)*assertTrue\(isinstance\((\w|\.|\'|\"|\[|\])+, "
                     "(\w|\.|\'|\"|\[|\])+\)\)")
asse_equal_type_re = re.compile(
                       r"(.)*assertEqual\(type\((\w|\.|\'|\"|\[|\])+\), "
                       "(\w|\.|\'|\"|\[|\])+\)")
asse_equal_end_with_none_re = re.compile(
                           r"assertEqual\(.*?,\s+None\)$")
asse_equal_start_with_none_re = re.compile(
                           r"assertEqual\(None,")
# NOTE(snikitin): Next two regexes weren't united to one for more readability.
#                 asse_true_false_with_in_or_not_in regex checks
#                 assertTrue/False(A in B) cases where B argument has no spaces
#                 asse_true_false_with_in_or_not_in_spaces regex checks cases
#                 where B argument has spaces and starts/ends with [, ', ".
#                 For example: [1, 2, 3], "some string", 'another string'.
#                 We have to separate these regexes to escape a false positives
#                 results. B argument should have spaces only if it starts
#                 with [, ", '. Otherwise checking of string
#                 "assertFalse(A in B and C in D)" will be false positives.
#                 In this case B argument is "B and C in D".
asse_true_false_with_in_or_not_in = re.compile(r"assert(True|False)\("
                    r"(\w|[][.'\"])+( not)? in (\w|[][.'\",])+(, .*)?\)")
asse_true_false_with_in_or_not_in_spaces = re.compile(r"assert(True|False)"
                    r"\((\w|[][.'\"])+( not)? in [\[|'|\"](\w|[][.'\", ])+"
                    r"[\[|'|\"](, .*)?\)")
conf_attribute_set_re = re.compile(r"CONF\.[a-z0-9_.]+\s*=\s*\w")
log_translation = re.compile(
    r"(.)*LOG\.(audit|error|critical)\(\s*('|\")")
log_translation_info = re.compile(
    r"(.)*LOG\.(info)\(\s*(_\(|'|\")")
log_translation_exception = re.compile(
    r"(.)*LOG\.(exception)\(\s*(_\(|'|\")")
log_translation_LW = re.compile(
    r"(.)*LOG\.(warning)\(\s*(_\(|'|\")")
log_warn = re.compile(
    r"(.)*LOG\.(warn)\(\s*('|\"|_)")
translated_log = re.compile(
    r"(.)*LOG\.(audit|error|info|critical|exception)"
    "\(\s*_\(\s*('|\")")
mutable_default_args = re.compile(r"^\s*def .+\((.+=\{\}|.+=\[\])")
string_translation = re.compile(r"[^_]*_\(\s*('|\")")
underscore_import_check = re.compile(r"(.)*import _(.)*")
# We need this for cases where they have created their own _ function.
custom_underscore_check = re.compile(r"(.)*_\s*=\s*(.)*")
api_version_re = re.compile(r"@.*api_version")

# TODO(dims): When other oslo libraries switch over non-namespace'd
# imports, we need to add them to the regexp below.
oslo_namespace_imports = re.compile(r"from[\s]*oslo[.](concurrency)")


class BaseASTChecker(ast.NodeVisitor):
    """Provides a simple framework for writing AST-based checks.

    Subclasses should implement visit_* methods like any other AST visitor
    implementation. When they detect an error for a particular node the
    method should call ``self.add_error(offending_node)``. Details about
    where in the code the error occurred will be pulled from the node
    object.

    Subclasses should also provide a class variable named CHECK_DESC to
    be used for the human readable error message.

    """

    def __init__(self, tree, filename):
        """This object is created automatically by pep8.

        :param tree: an AST tree
        :param filename: name of the file being analyzed
                         (ignored by our checks)
        """
        self._tree = tree
        self._errors = []

    def run(self):
        """Called automatically by pep8."""
        self.visit(self._tree)
        return self._errors

    def add_error(self, node, message=None):
        """Add an error caused by a node to the list of errors for pep8."""
        message = message or self.CHECK_DESC
        error = (node.lineno, node.col_offset, message, self.__class__)
        self._errors.append(error)

    def _check_call_names(self, call_node, names):
        if isinstance(call_node, ast.Call):
            if isinstance(call_node.func, ast.Name):
                if call_node.func.id in names:
                    return True
        return False


def import_no_db_in_virt(logical_line, filename):
    """Check for db calls from nova/virt

    As of grizzly-2 all the database calls have been removed from
    nova/virt, and we want to keep it that way.

    N307
    """
    if "nova/virt" in filename and not filename.endswith("fake.py"):
        if logical_line.startswith("from nova import db"):
            yield (0, "N307: nova.db import not allowed in nova/virt/*")


def no_db_session_in_public_api(logical_line, filename):
    if "db/api.py" in filename:
        if session_check.match(logical_line):
            yield (0, "N309: public db api methods may not accept session")


def use_timeutils_utcnow(logical_line, filename):
    # tools are OK to use the standard datetime module
    if "/tools/" in filename:
        return

    msg = "N310: timeutils.utcnow() must be used instead of datetime.%s()"

    datetime_funcs = ['now', 'utcnow']
    for f in datetime_funcs:
        pos = logical_line.find('datetime.%s' % f)
        if pos != -1:
            yield (pos, msg % f)


def _get_virt_name(regex, data):
    m = regex.match(data)
    if m is None:
        return None
    driver = m.group(1)
    # Ignore things we mis-detect as virt drivers in the regex
    if driver in ["test_virt_drivers", "driver", "firewall",
                  "disk", "api", "imagecache", "cpu", "hardware"]:
        return None
    # TODO(berrange): remove once bugs 1261826 and 126182 are
    # fixed, or baremetal driver is removed, which is first.
    if driver == "baremetal":
        return None
    return driver


def import_no_virt_driver_import_deps(physical_line, filename):
    """Check virt drivers' modules aren't imported by other drivers

    Modules under each virt driver's directory are
    considered private to that virt driver. Other drivers
    in Nova must not access those drivers. Any code that
    is to be shared should be refactored into a common
    module

    N311
    """
    thisdriver = _get_virt_name(virt_file_re, filename)
    thatdriver = _get_virt_name(virt_import_re, physical_line)
    if (thatdriver is not None and
        thisdriver is not None and
        thisdriver != thatdriver):
        return (0, "N311: importing code from other virt drivers forbidden")


def import_no_virt_driver_config_deps(physical_line, filename):
    """Check virt drivers' config vars aren't used by other drivers

    Modules under each virt driver's directory are
    considered private to that virt driver. Other drivers
    in Nova must not use their config vars. Any config vars
    that are to be shared should be moved into a common module

    N312
    """
    thisdriver = _get_virt_name(virt_file_re, filename)
    thatdriver = _get_virt_name(virt_config_re, physical_line)
    if (thatdriver is not None and
        thisdriver is not None and
        thisdriver != thatdriver):
        return (0, "N312: using config vars from other virt drivers forbidden")


def capital_cfg_help(logical_line, tokens):
    msg = "N313: capitalize help string"

    if cfg_re.match(logical_line):
        for t in range(len(tokens)):
            if tokens[t][1] == "help":
                txt = tokens[t + 2][1]
                if len(txt) > 1 and txt[1].islower():
                    yield(0, msg)


def no_vi_headers(physical_line, line_number, lines):
    """Check for vi editor configuration in source files.

    By default vi modelines can only appear in the first or
    last 5 lines of a source file.

    N314
    """
    # NOTE(gilliard): line_number is 1-indexed
    if line_number <= 5 or line_number > len(lines) - 5:
        if vi_header_re.match(physical_line):
            return 0, "N314: Don't put vi configuration in source files"


def assert_true_instance(logical_line):
    """Check for assertTrue(isinstance(a, b)) sentences

    N316
    """
    if asse_trueinst_re.match(logical_line):
        yield (0, "N316: assertTrue(isinstance(a, b)) sentences not allowed")


def assert_equal_type(logical_line):
    """Check for assertEqual(type(A), B) sentences

    N317
    """
    if asse_equal_type_re.match(logical_line):
        yield (0, "N317: assertEqual(type(A), B) sentences not allowed")


def assert_equal_none(logical_line):
    """Check for assertEqual(A, None) or assertEqual(None, A) sentences

    N318
    """
    res = (asse_equal_start_with_none_re.search(logical_line) or
           asse_equal_end_with_none_re.search(logical_line))
    if res:
        yield (0, "N318: assertEqual(A, None) or assertEqual(None, A) "
               "sentences not allowed")


def no_translate_debug_logs(logical_line, filename):
    """Check for 'LOG.debug(_('

    As per our translation policy,
    https://wiki.openstack.org/wiki/LoggingStandards#Log_Translation
    we shouldn't translate debug level logs.

    * This check assumes that 'LOG' is a logger.
    * Use filename so we can start enforcing this in specific folders instead
      of needing to do so all at once.

    N319
    """
    if logical_line.startswith("LOG.debug(_("):
        yield(0, "N319 Don't translate debug level logs")


def no_setting_conf_directly_in_tests(logical_line, filename):
    """Check for setting CONF.* attributes directly in tests

    The value can leak out of tests affecting how subsequent tests run.
    Using self.flags(option=value) is the preferred method to temporarily
    set config options in tests.

    N320
    """
    if 'nova/tests/' in filename:
        res = conf_attribute_set_re.match(logical_line)
        if res:
            yield (0, "N320: Setting CONF.* attributes directly in tests is "
                      "forbidden. Use self.flags(option=value) instead")


def validate_log_translations(logical_line, physical_line, filename):
    # Translations are not required in the test directory
    # and the Xen utilities
    if ("nova/tests" in filename or
        "plugins/xenserver/xenapi/etc/xapi.d" in filename or
        # TODO(Mike_D):Needs to be remove with:
        # I075ab2a522272f2082c292dfedc877abd8ebe328
            "nova/virt/libvirt" in filename):
        return
    if pep8.noqa(physical_line):
        return
    msg = "N328: LOG.info messages require translations `_LI()`!"
    if log_translation_info.match(logical_line):
        yield (0, msg)
    msg = "N329: LOG.exception messages require translations `_LE()`!"
    if log_translation_exception.match(logical_line):
        yield (0, msg)
    msg = "N330: LOG.warning messages require translations `_LW()`!"
    if log_translation_LW.match(logical_line):
        yield (0, msg)
    msg = "N331: Use LOG.warning due to compatibility with py3"
    if log_warn.match(logical_line):
        yield (0, msg)
    msg = "N321: Log messages require translations!"
    if log_translation.match(logical_line):
        yield (0, msg)


def no_mutable_default_args(logical_line):
    msg = "N322: Method's default argument shouldn't be mutable!"
    if mutable_default_args.match(logical_line):
        yield (0, msg)


def check_explicit_underscore_import(logical_line, filename):
    """Check for explicit import of the _ function

    We need to ensure that any files that are using the _() function
    to translate logs are explicitly importing the _ function.  We
    can't trust unit test to catch whether the import has been
    added so we need to check for it here.
    """

    # Build a list of the files that have _ imported.  No further
    # checking needed once it is found.
    if filename in UNDERSCORE_IMPORT_FILES:
        pass
    elif (underscore_import_check.match(logical_line) or
          custom_underscore_check.match(logical_line)):
        UNDERSCORE_IMPORT_FILES.append(filename)
    elif (translated_log.match(logical_line) or
         string_translation.match(logical_line)):
        yield(0, "N323: Found use of _() without explicit import of _ !")


def use_jsonutils(logical_line, filename):
    # the code below that path is not meant to be executed from neutron
    # tree where jsonutils module is present, so don't enforce its usage
    # for this subdirectory
    if "plugins/xenserver" in filename:
        return

    # tools are OK to use the standard json module
    if "/tools/" in filename:
        return

    msg = "N324: jsonutils.%(fun)s must be used instead of json.%(fun)s"

    if "json." in logical_line:
        json_funcs = ['dumps(', 'dump(', 'loads(', 'load(']
        for f in json_funcs:
            pos = logical_line.find('json.%s' % f)
            if pos != -1:
                yield (pos, msg % {'fun': f[:-1]})


def check_api_version_decorator(logical_line, blank_before, filename):
    msg = ("N332: the api_version decorator must be the first decorator"
           " on a method.")
    if blank_before == 0 and re.match(api_version_re, logical_line):
        yield(0, msg)


class CheckForStrUnicodeExc(BaseASTChecker):
    """Checks for the use of str() or unicode() on an exception.

    This currently only handles the case where str() or unicode()
    is used in the scope of an exception handler.  If the exception
    is passed into a function, returned from an assertRaises, or
    used on an exception created in the same scope, this does not
    catch it.
    """

    CHECK_DESC = ('N325 str() and unicode() cannot be used on an '
                  'exception.  Remove or use six.text_type()')

    def __init__(self, tree, filename):
        super(CheckForStrUnicodeExc, self).__init__(tree, filename)
        self.name = []
        self.already_checked = []

    def visit_TryExcept(self, node):
        for handler in node.handlers:
            if handler.name:
                self.name.append(handler.name.id)
                super(CheckForStrUnicodeExc, self).generic_visit(node)
                self.name = self.name[:-1]
            else:
                super(CheckForStrUnicodeExc, self).generic_visit(node)

    def visit_Call(self, node):
        if self._check_call_names(node, ['str', 'unicode']):
            if node not in self.already_checked:
                self.already_checked.append(node)
                if isinstance(node.args[0], ast.Name):
                    if node.args[0].id in self.name:
                        self.add_error(node.args[0])
        super(CheckForStrUnicodeExc, self).generic_visit(node)


class CheckForTransAdd(BaseASTChecker):
    """Checks for the use of concatenation on a translated string.

    Translations should not be concatenated with other strings, but
    should instead include the string being added to the translated
    string to give the translators the most information.
    """

    CHECK_DESC = ('N326 Translated messages cannot be concatenated.  '
                  'String should be included in translated message.')

    TRANS_FUNC = ['_', '_LI', '_LW', '_LE', '_LC']

    def visit_BinOp(self, node):
        if isinstance(node.op, ast.Add):
            if self._check_call_names(node.left, self.TRANS_FUNC):
                self.add_error(node.left)
            elif self._check_call_names(node.right, self.TRANS_FUNC):
                self.add_error(node.right)
        super(CheckForTransAdd, self).generic_visit(node)


def check_oslo_namespace_imports(logical_line, blank_before, filename):
    if re.match(oslo_namespace_imports, logical_line):
        msg = ("N333: '%s' must be used instead of '%s'.") % (
               logical_line.replace('oslo.', 'oslo_'),
               logical_line)
        yield(0, msg)


def assert_true_or_false_with_in(logical_line):
    """Check for assertTrue/False(A in B), assertTrue/False(A not in B),
    assertTrue/False(A in B, message) or assertTrue/False(A not in B, message)
    sentences.

    N334
    """
    res = (asse_true_false_with_in_or_not_in.search(logical_line) or
           asse_true_false_with_in_or_not_in_spaces.search(logical_line))
    if res:
        yield (0, "N334: Use assertIn/NotIn(A, B) rather than "
                  "assertTrue/False(A in/not in B) when checking collection "
                  "contents.")


def factory(register):
    register(import_no_db_in_virt)
    register(no_db_session_in_public_api)
    register(use_timeutils_utcnow)
    register(import_no_virt_driver_import_deps)
    register(import_no_virt_driver_config_deps)
    register(capital_cfg_help)
    register(no_vi_headers)
    register(assert_true_instance)
    register(assert_equal_type)
    register(assert_equal_none)
    register(no_translate_debug_logs)
    register(no_setting_conf_directly_in_tests)
    register(validate_log_translations)
    register(no_mutable_default_args)
    register(check_explicit_underscore_import)
    register(use_jsonutils)
    register(check_api_version_decorator)
    register(CheckForStrUnicodeExc)
    register(CheckForTransAdd)
    register(check_oslo_namespace_imports)
    register(assert_true_or_false_with_in)
