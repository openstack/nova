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

"""
Guidelines for writing new hacking checks

 - Use only for Nova specific tests. OpenStack general tests
   should be submitted to the common 'hacking' module.
 - Pick numbers in the range N3xx. Find the current test with
   the highest allocated number and then pick the next value.
 - Keep the test method code in the source file ordered based
   on the N3xx value.
 - List the new rule in the top level HACKING.rst file
 - Add test cases for each new rule to nova/tests/unit/test_hacking.py

"""

import ast
import os
import re

from hacking import core
import six


UNDERSCORE_IMPORT_FILES = []

session_check = re.compile(r"\w*def [a-zA-Z0-9].*[(].*session.*[)]")
cfg_re = re.compile(r".*\scfg\.")
# Excludes oslo.config OptGroup objects
cfg_opt_re = re.compile(r".*[\s\[]cfg\.[a-zA-Z]*Opt\(")
rule_default_re = re.compile(r".*RuleDefault\(")
policy_enforce_re = re.compile(r".*_ENFORCER\.enforce\(")
virt_file_re = re.compile(r"\./nova/(?:tests/)?virt/(\w+)/")
virt_import_re = re.compile(
    r"^\s*(?:import|from) nova\.(?:tests\.)?virt\.(\w+)")
virt_config_re = re.compile(
    r"CONF\.import_opt\('.*?', 'nova\.virt\.(\w+)('|.)")
asse_trueinst_re = re.compile(
                     r"(.)*assertTrue\(isinstance\((\w|\.|\'|\"|\[|\])+, "
                     r"(\w|\.|\'|\"|\[|\])+\)\)")
asse_equal_type_re = re.compile(
                       r"(.)*assertEqual\(type\((\w|\.|\'|\"|\[|\])+\), "
                       r"(\w|\.|\'|\"|\[|\])+\)")
asse_equal_in_end_with_true_or_false_re = re.compile(r"assertEqual\("
                    r"(\w|[][.'\"])+ in (\w|[][.'\", ])+, (True|False)\)")
asse_equal_in_start_with_true_or_false_re = re.compile(r"assertEqual\("
                    r"(True|False), (\w|[][.'\"])+ in (\w|[][.'\", ])+\)")
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
asse_raises_regexp = re.compile(r"assertRaisesRegexp\(")
conf_attribute_set_re = re.compile(r"CONF\.[a-z0-9_.]+\s*=\s*\w")
translated_log = re.compile(
    r"(.)*LOG\.(audit|error|info|critical|exception)"
    r"\(\s*_\(\s*('|\")")
mutable_default_args = re.compile(r"^\s*def .+\((.+=\{\}|.+=\[\])")
string_translation = re.compile(r"[^_]*_\(\s*('|\")")
underscore_import_check = re.compile(r"(.)*import _(.)*")
import_translation_for_log_or_exception = re.compile(
    r"(.)*(from\snova.i18n\simport)\s_")
# We need this for cases where they have created their own _ function.
custom_underscore_check = re.compile(r"(.)*_\s*=\s*(.)*")
api_version_re = re.compile(r"@.*\bapi_version\b")
dict_constructor_with_list_copy_re = re.compile(r".*\bdict\((\[)?(\(|\[)")
decorator_re = re.compile(r"@.*")
http_not_implemented_re = re.compile(r"raise .*HTTPNotImplemented\(")
spawn_re = re.compile(
    r".*(eventlet|greenthread)\.(?P<spawn_part>spawn(_n)?)\(.*\)")
contextlib_nested = re.compile(r"^with (contextlib\.)?nested\(")
doubled_words_re = re.compile(
    r"\b(then?|[iao]n|i[fst]|but|f?or|at|and|[dt]o)\s+\1\b")
log_remove_context = re.compile(
    r"(.)*LOG\.(.*)\(.*(context=[_a-zA-Z0-9].*)+.*\)")
return_not_followed_by_space = re.compile(r"^\s*return(?:\(|{|\"|'|#).*$")
uuid4_re = re.compile(r"uuid4\(\)($|[^\.]|\.hex)")
redundant_import_alias_re = re.compile(r"import (?:.*\.)?(.+) as \1$")
yield_not_followed_by_space = re.compile(r"^\s*yield(?:\(|{|\[|\"|').*$")
asse_regexpmatches = re.compile(
    r"(assertRegexpMatches|assertNotRegexpMatches)\(")
privsep_file_re = re.compile('^nova/privsep[./]')
privsep_import_re = re.compile(
    r"^(?:import|from).*\bprivsep\b")
# Redundant parenthetical masquerading as a tuple, used with ``in``:
# Space, "in", space, open paren
# Optional single or double quote (so we match strings or symbols)
# A sequence of the characters that can make up a symbol. (This is weak: a
#   string can contain other characters; and a numeric symbol can start with a
#   minus, and a method call has a param list, and... Not sure this gets better
#   without a lexer.)
# The same closing quote
# Close paren
disguised_as_tuple_re = re.compile(r''' in \((['"]?)[a-zA-Z0-9_.]+\1\)''')

# NOTE(takashin): The patterns of nox-existent mock assertion methods and
# attributes do not cover all cases. If you find a new pattern,
# add the pattern in the following regex patterns.
mock_assert_method_re = re.compile(
    r"\.((called_once(_with)*|has_calls)|"
    r"mock_assert_(called(_(once|with|once_with))?"
    r"|any_call|has_calls|not_called)|"
    r"(asser|asset|asssert|assset)_(called(_(once|with|once_with))?"
    r"|any_call|has_calls|not_called))\(")
mock_attribute_re = re.compile(r"[\.\(](retrun_value)[,=\s]")
# Regex for useless assertions
useless_assertion_re = re.compile(
    r"\.((assertIsNone)\(None|(assertTrue)\((True|\d+|'.+'|\".+\")),")


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
        """This object is created automatically by pycodestyle.

        :param tree: an AST tree
        :param filename: name of the file being analyzed
                         (ignored by our checks)
        """
        self._tree = tree
        self._errors = []

    def run(self):
        """Called automatically by pycodestyle."""
        self.visit(self._tree)
        return self._errors

    def add_error(self, node, message=None):
        """Add an error caused by a node to the list of errors."""
        message = message or self.CHECK_DESC
        error = (node.lineno, node.col_offset, message, self.__class__)
        self._errors.append(error)

    def _check_call_names(self, call_node, names):
        if isinstance(call_node, ast.Call):
            if isinstance(call_node.func, ast.Name):
                if call_node.func.id in names:
                    return True
        return False


@core.flake8ext
def import_no_db_in_virt(logical_line, filename):
    """Check for db calls from nova/virt

    As of grizzly-2 all the database calls have been removed from
    nova/virt, and we want to keep it that way.

    N307
    """
    if "nova/virt" in filename and not filename.endswith("fake.py"):
        if logical_line.startswith("from nova.db import api"):
            yield (0, "N307: nova.db.api import not allowed in nova/virt/*")


@core.flake8ext
def no_db_session_in_public_api(logical_line, filename):
    if "db/api.py" in filename:
        if session_check.match(logical_line):
            yield (0, "N309: public db api methods may not accept session")


@core.flake8ext
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
    if driver in ["test_virt_drivers", "driver", "disk", "api", "imagecache",
                  "cpu", "hardware", "image"]:
        return None
    return driver


@core.flake8ext
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


@core.flake8ext
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


@core.flake8ext
def capital_cfg_help(logical_line, tokens):
    msg = "N313: capitalize help string"

    if cfg_re.match(logical_line):
        for t in range(len(tokens)):
            if tokens[t][1] == "help":
                txt = tokens[t + 2][1]
                if len(txt) > 1 and txt[1].islower():
                    yield (0, msg)


@core.flake8ext
def assert_true_instance(logical_line):
    """Check for assertTrue(isinstance(a, b)) sentences

    N316
    """
    if asse_trueinst_re.match(logical_line):
        yield (0, "N316: assertTrue(isinstance(a, b)) sentences not allowed")


@core.flake8ext
def assert_equal_type(logical_line):
    """Check for assertEqual(type(A), B) sentences

    N317
    """
    if asse_equal_type_re.match(logical_line):
        yield (0, "N317: assertEqual(type(A), B) sentences not allowed")


@core.flake8ext
def check_python3_xrange(logical_line):
    if re.search(r"\bxrange\s*\(", logical_line):
        yield (0, "N327: Do not use xrange(). 'xrange()' is not compatible "
                  "with Python 3. Use range() or six.moves.range() instead.")


@core.flake8ext
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
        yield (0, "N319 Don't translate debug level logs")


@core.flake8ext
def no_import_translation_in_tests(logical_line, filename):
    """Check for 'from nova.i18n import _'
    N337
    """
    if 'nova/tests/' in filename:
        res = import_translation_for_log_or_exception.match(logical_line)
        if res:
            yield (0, "N337 Don't import translation in tests")


@core.flake8ext
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


@core.flake8ext
def no_mutable_default_args(logical_line):
    msg = "N322: Method's default argument shouldn't be mutable!"
    if mutable_default_args.match(logical_line):
        yield (0, msg)


@core.flake8ext
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
        yield (0, "N323: Found use of _() without explicit import of _ !")


@core.flake8ext
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


@core.flake8ext
def check_api_version_decorator(logical_line, previous_logical, blank_before,
                                filename):
    msg = ("N332: the api_version decorator must be the first decorator"
           " on a method.")
    if blank_before == 0 and re.match(api_version_re, logical_line) \
           and re.match(decorator_re, previous_logical):
        yield (0, msg)


class CheckForStrUnicodeExc(BaseASTChecker):
    """Checks for the use of str() or unicode() on an exception.

    This currently only handles the case where str() or unicode()
    is used in the scope of an exception handler.  If the exception
    is passed into a function, returned from an assertRaises, or
    used on an exception created in the same scope, this does not
    catch it.
    """

    name = 'check_for_string_unicode_exc'
    version = '1.0'

    CHECK_DESC = ('N325 str() and unicode() cannot be used on an '
                  'exception.  Remove or use six.text_type()')

    def __init__(self, tree, filename):
        super(CheckForStrUnicodeExc, self).__init__(tree, filename)
        self.name = []
        self.already_checked = []

    # Python 2 produces ast.TryExcept and ast.TryFinally nodes, but Python 3
    # only produces ast.Try nodes.
    if six.PY2:
        def visit_TryExcept(self, node):
            for handler in node.handlers:
                if handler.name:
                    self.name.append(handler.name.id)
                    super(CheckForStrUnicodeExc, self).generic_visit(node)
                    self.name = self.name[:-1]
                else:
                    super(CheckForStrUnicodeExc, self).generic_visit(node)
    else:
        def visit_Try(self, node):
            for handler in node.handlers:
                if handler.name:
                    self.name.append(handler.name)
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

    name = 'check_for_trans_add'
    version = '0.1'

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


class _FindVariableReferences(ast.NodeVisitor):
    def __init__(self):
        super(_FindVariableReferences, self).__init__()
        self._references = []

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            # This means the value of a variable was loaded. For example a
            # variable 'foo' was used like:
            # mocked_thing.bar = foo
            # foo()
            # self.assertRaises(exception, foo)
            self._references.append(node.id)
        super(_FindVariableReferences, self).generic_visit(node)


class CheckForUncalledTestClosure(BaseASTChecker):
    """Look for closures that are never called in tests.

    A recurring pattern when using multiple mocks is to create a closure
    decorated with mocks like:

    def test_thing(self):
            @mock.patch.object(self.compute, 'foo')
            @mock.patch.object(self.compute, 'bar')
            def _do_test(mock_bar, mock_foo):
                # Test things
        _do_test()

    However it is easy to leave off the _do_test() and have the test pass
    because nothing runs. This check looks for methods defined within a test
    method and ensures that there is a reference to them. Only methods defined
    one level deep are checked. Something like:

    def test_thing(self):
        class FakeThing:
            def foo(self):

    would not ensure that foo is referenced.

    N349
    """

    name = 'check_for_uncalled_test_closure'
    version = '0.1'

    def __init__(self, tree, filename):
        super(CheckForUncalledTestClosure, self).__init__(tree, filename)
        self._filename = filename

    def visit_FunctionDef(self, node):
        # self._filename is 'stdin' in the unit test for this check.
        if (not os.path.basename(self._filename).startswith('test_') and
                os.path.basename(self._filename) != 'stdin'):
            return

        closures = []
        references = []
        # Walk just the direct nodes of the test method
        for child_node in ast.iter_child_nodes(node):
            if isinstance(child_node, ast.FunctionDef):
                closures.append(child_node.name)

        # Walk all nodes to find references
        find_references = _FindVariableReferences()
        find_references.generic_visit(node)
        references = find_references._references

        missed = set(closures) - set(references)
        if missed:
            self.add_error(node, 'N349: Test closures not called: %s'
                    % ','.join(missed))


@core.flake8ext
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


@core.flake8ext
def assert_raises_regexp(logical_line):
    """Check for usage of deprecated assertRaisesRegexp

    N335
    """
    res = asse_raises_regexp.search(logical_line)
    if res:
        yield (0, "N335: assertRaisesRegex must be used instead "
                  "of assertRaisesRegexp")


@core.flake8ext
def dict_constructor_with_list_copy(logical_line):
    msg = ("N336: Must use a dict comprehension instead of a dict constructor"
           " with a sequence of key-value pairs."
           )
    if dict_constructor_with_list_copy_re.match(logical_line):
        yield (0, msg)


@core.flake8ext
def assert_equal_in(logical_line):
    """Check for assertEqual(A in B, True), assertEqual(True, A in B),
    assertEqual(A in B, False) or assertEqual(False, A in B) sentences

    N338
    """
    res = (asse_equal_in_start_with_true_or_false_re.search(logical_line) or
           asse_equal_in_end_with_true_or_false_re.search(logical_line))
    if res:
        yield (0, "N338: Use assertIn/NotIn(A, B) rather than "
                  "assertEqual(A in B, True/False) when checking collection "
                  "contents.")


@core.flake8ext
def check_http_not_implemented(logical_line, filename, noqa):
    msg = ("N339: HTTPNotImplemented response must be implemented with"
           " common raise_feature_not_supported().")
    if noqa:
        return
    if ("nova/api/openstack/compute" not in filename):
        return
    if re.match(http_not_implemented_re, logical_line):
        yield (0, msg)


@core.flake8ext
def check_greenthread_spawns(logical_line, filename):
    """Check for use of greenthread.spawn(), greenthread.spawn_n(),
    eventlet.spawn(), and eventlet.spawn_n()

    N340
    """
    msg = ("N340: Use nova.utils.%(spawn)s() rather than "
           "greenthread.%(spawn)s() and eventlet.%(spawn)s()")
    if "nova/utils.py" in filename or "nova/tests/" in filename:
        return

    match = re.match(spawn_re, logical_line)

    if match:
        yield (0, msg % {'spawn': match.group('spawn_part')})


@core.flake8ext
def check_no_contextlib_nested(logical_line, filename):
    msg = ("N341: contextlib.nested is deprecated. With Python 2.7 and later "
           "the with-statement supports multiple nested objects. See https://"
           "docs.python.org/2/library/contextlib.html#contextlib.nested for "
           "more information. nova.test.nested() is an alternative as well.")

    if contextlib_nested.match(logical_line):
        yield (0, msg)


@core.flake8ext
def check_config_option_in_central_place(logical_line, filename):
    msg = ("N342: Config options should be in the central location "
           "'/nova/conf/*'. Do not declare new config options outside "
           "of that folder.")
    # That's the correct location
    if "nova/conf/" in filename:
        return

    # (macsz) All config options (with exceptions that are clarified
    # in the list below) were moved to the central place. List below is for
    # all options that were impossible to move without doing a major impact
    # on code. Add full path to a module or folder.
    conf_exceptions = [
        # CLI opts are allowed to be outside of nova/conf directory
        'nova/cmd/manage.py',
        'nova/cmd/policy.py',
        'nova/cmd/status.py',
        # config options should not be declared in tests, but there is
        # another checker for it (N320)
        'nova/tests',
    ]

    if any(f in filename for f in conf_exceptions):
        return

    if cfg_opt_re.match(logical_line):
        yield (0, msg)


@core.flake8ext
def check_policy_registration_in_central_place(logical_line, filename):
    msg = ('N350: Policy registration should be in the central location(s) '
           '"/nova/policies/*"')
    # This is where registration should happen
    if "nova/policies/" in filename:
        return
    # A couple of policy tests register rules
    if "nova/tests/unit/test_policy.py" in filename:
        return

    if rule_default_re.match(logical_line):
        yield (0, msg)


@core.flake8ext
def check_policy_enforce(logical_line, filename):
    """Look for uses of nova.policy._ENFORCER.enforce()

    Now that policy defaults are registered in code the _ENFORCER.authorize
    method should be used. That ensures that only registered policies are used.
    Uses of _ENFORCER.enforce could allow unregistered policies to be used, so
    this check looks for uses of that method.

    N351
    """

    msg = ('N351: nova.policy._ENFORCER.enforce() should not be used. '
           'Use the authorize() method instead.')

    if policy_enforce_re.match(logical_line):
        yield (0, msg)


@core.flake8ext
def check_doubled_words(physical_line, filename):
    """Check for the common doubled-word typos

    N343
    """
    msg = ("N343: Doubled word '%(word)s' typo found")

    match = re.search(doubled_words_re, physical_line)

    if match:
        return (0, msg % {'word': match.group(1)})


@core.flake8ext
def check_python3_no_iteritems(logical_line):
    msg = ("N344: Use items() instead of dict.iteritems().")

    if re.search(r".*\.iteritems\(\)", logical_line):
        yield (0, msg)


@core.flake8ext
def check_python3_no_iterkeys(logical_line):
    msg = ("N345: Use six.iterkeys() instead of dict.iterkeys().")

    if re.search(r".*\.iterkeys\(\)", logical_line):
        yield (0, msg)


@core.flake8ext
def check_python3_no_itervalues(logical_line):
    msg = ("N346: Use six.itervalues() instead of dict.itervalues().")

    if re.search(r".*\.itervalues\(\)", logical_line):
        yield (0, msg)


@core.flake8ext
def no_os_popen(logical_line):
    """Disallow 'os.popen('

    Deprecated library function os.popen() Replace it using subprocess
    https://bugs.launchpad.net/tempest/+bug/1529836

    N348
    """

    if 'os.popen(' in logical_line:
        yield (0, 'N348 Deprecated library function os.popen(). '
                  'Replace it using subprocess module. ')


@core.flake8ext
def no_log_warn(logical_line):
    """Disallow 'LOG.warn('

    Deprecated LOG.warn(), instead use LOG.warning
    https://bugs.launchpad.net/senlin/+bug/1508442

    N352
    """

    msg = ("N352: LOG.warn is deprecated, please use LOG.warning!")
    if "LOG.warn(" in logical_line:
        yield (0, msg)


@core.flake8ext
def check_context_log(logical_line, filename, noqa):
    """check whether context is being passed to the logs

    Not correct: LOG.info(_LI("Rebooting instance"), context=context)
    Correct:  LOG.info(_LI("Rebooting instance"))
    https://bugs.launchpad.net/nova/+bug/1500896

    N353
    """
    if noqa:
        return

    if "nova/tests" in filename:
        return

    if log_remove_context.match(logical_line):
        yield (0,
               "N353: Nova is using oslo.context's RequestContext "
               "which means the context object is in scope when "
               "doing logging using oslo.log, so no need to pass it as "
               "kwarg.")


@core.flake8ext
def no_assert_equal_true_false(logical_line):
    """Enforce use of assertTrue/assertFalse.

    Prevent use of assertEqual(A, True|False), assertEqual(True|False, A),
    assertNotEqual(A, True|False), and assertNotEqual(True|False, A).

    N355
    """
    _start_re = re.compile(r'assert(Not)?Equal\((True|False),')
    _end_re = re.compile(r'assert(Not)?Equal\(.*,\s+(True|False)\)$')

    if _start_re.search(logical_line) or _end_re.search(logical_line):
        yield (0, "N355: assertEqual(A, True|False), "
               "assertEqual(True|False, A), assertNotEqual(A, True|False), "
               "or assertEqual(True|False, A) sentences must not be used. "
               "Use assertTrue(A) or assertFalse(A) instead")


@core.flake8ext
def no_assert_true_false_is_not(logical_line):
    """Enforce use of assertIs/assertIsNot.

    Prevent use of assertTrue(A is|is not B) and assertFalse(A is|is not B).

    N356
    """
    _re = re.compile(r'assert(True|False)\(.+\s+is\s+(not\s+)?.+\)$')

    if _re.search(logical_line):
        yield (0, "N356: assertTrue(A is|is not B) or "
               "assertFalse(A is|is not B) sentences must not be used. "
               "Use assertIs(A, B) or assertIsNot(A, B) instead")


@core.flake8ext
def check_uuid4(logical_line):
    """Generating UUID

    Use oslo_utils.uuidutils or uuidsentinel(in case of test cases) to generate
    UUID instead of uuid4().

    N357
    """

    msg = ("N357: Use oslo_utils.uuidutils or uuidsentinel(in case of test "
           "cases) to generate UUID instead of uuid4().")

    if uuid4_re.search(logical_line):
        yield (0, msg)


@core.flake8ext
def return_followed_by_space(logical_line):
    """Return should be followed by a space.

    Return should be followed by a space to clarify that return is
    not a function. Adding a space may force the developer to rethink
    if there are unnecessary parentheses in the written code.

    Not correct: return(42), return(a, b)
    Correct: return, return 42, return (a, b), return a, b

    N358
    """
    if return_not_followed_by_space.match(logical_line):
        yield (0,
               "N358: Return keyword should be followed by a space.")


@core.flake8ext
def no_redundant_import_alias(logical_line):
    """Check for redundant import aliases.

    Imports should not be in the forms below.

    from x import y as y
    import x as x
    import x.y as y

    N359
    """
    if re.search(redundant_import_alias_re, logical_line):
        yield (0, "N359: Import alias should not be redundant.")


@core.flake8ext
def yield_followed_by_space(logical_line):
    """Yield should be followed by a space.

    Yield should be followed by a space to clarify that yield is
    not a function. Adding a space may force the developer to rethink
    if there are unnecessary parentheses in the written code.

    Not correct: yield(x), yield(a, b)
    Correct: yield x, yield (a, b), yield a, b

    N360
    """
    if yield_not_followed_by_space.match(logical_line):
        yield (0,
               "N360: Yield keyword should be followed by a space.")


@core.flake8ext
def assert_regexpmatches(logical_line):
    """Check for usage of deprecated assertRegexpMatches/assertNotRegexpMatches

    N361
    """
    res = asse_regexpmatches.search(logical_line)
    if res:
        yield (0, "N361: assertRegex/assertNotRegex must be used instead "
                  "of assertRegexpMatches/assertNotRegexpMatches.")


@core.flake8ext
def privsep_imports_not_aliased(logical_line, filename):
    """Do not abbreviate or alias privsep module imports.

    When accessing symbols under nova.privsep in code or tests, the full module
    path (e.g. nova.privsep.path.readfile(...)) should be used
    explicitly rather than importing and using an alias/abbreviation such as:

      from nova.privsep import path
      ...
      path.readfile(...)

    See Ief177dbcb018da6fbad13bb0ff153fc47292d5b9.

    N362
    """
    if (
            # Give modules under nova.privsep a pass
            not privsep_file_re.match(filename) and
            # Any style of import of privsep...
            privsep_import_re.match(logical_line) and
            # ...that isn't 'import nova.privsep[.foo...]'
            logical_line.count(' ') > 1):
        yield (0, "N362: always import privsep modules so that the use of "
                  "escalated permissions is obvious to callers. For example, "
                  "use 'import nova.privsep.path' instead of "
                  "'from nova.privsep import path'.")


@core.flake8ext
def did_you_mean_tuple(logical_line):
    """Disallow ``(not_a_tuple)`` because you meant ``(a_tuple_of_one,)``.

    N363
    """
    if disguised_as_tuple_re.search(logical_line):
        yield (0, "N363: You said ``in (not_a_tuple)`` when you almost "
                  "certainly meant ``in (a_tuple_of_one,)``.")


@core.flake8ext
def nonexistent_assertion_methods_and_attributes(logical_line, filename):
    """Check non-existent mock assertion methods and attributes.

    The following assertion methods do not exist.

    - called_once()
    - called_once_with()
    - has_calls()
    - mock_assert_*()

    The following typos were found in the past cases.

    - asser_*
    - asset_*
    - assset_*
    - asssert_*
    - retrun_value

    N364
    """
    msg = ("N364: Non existent mock assertion method or attribute (%s) is "
           "used. Check a typo or whether the assertion method should begin "
           "with 'assert_'.")
    if 'nova/tests/' in filename:
        match = mock_assert_method_re.search(logical_line)
        if match:
            yield (0, msg % match.group(1))

        match = mock_attribute_re.search(logical_line)
        if match:
            yield (0, msg % match.group(1))


@core.flake8ext
def useless_assertion(logical_line, filename):
    """Check useless assertions in tests.

    The following assertions are useless.

    - assertIsNone(None, ...)
    - assertTrue(True, ...)
    - assertTrue(2, ...)   # Constant number
    - assertTrue('Constant string', ...)
    - assertTrue("Constant string", ...)

    They are usually misuses of assertIsNone or assertTrue.

    N365
    """
    msg = "N365: Misuse of %s."
    if 'nova/tests/' in filename:
        match = useless_assertion_re.search(logical_line)
        if match:
            yield (0, msg % (match.group(2) or match.group(3)))
