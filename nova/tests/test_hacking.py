#    Copyright 2014 Red Hat, Inc.
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

import textwrap

import mock
import pep8

from nova.hacking import checks
from nova import test


class HackingTestCase(test.NoDBTestCase):
    """This class tests the hacking checks in nova.hacking.checks by passing
    strings to the check methods like the pep8/flake8 parser would. The parser
    loops over each line in the file and then passes the parameters to the
    check method. The parameter names in the check method dictate what type of
    object is passed to the check method. The parameter types are::

        logical_line: A processed line with the following modifications:
            - Multi-line statements converted to a single line.
            - Stripped left and right.
            - Contents of strings replaced with "xxx" of same length.
            - Comments removed.
        physical_line: Raw line of text from the input file.
        lines: a list of the raw lines from the input file
        tokens: the tokens that contribute to this logical line
        line_number: line number in the input file
        total_lines: number of lines in the input file
        blank_lines: blank lines before this one
        indent_char: indentation character in this file (" " or "\t")
        indent_level: indentation (with tabs expanded to multiples of 8)
        previous_indent_level: indentation on previous line
        previous_logical: previous logical line
        filename: Path of the file being run through pep8

    When running a test on a check method the return will be False/None if
    there is no violation in the sample input. If there is an error a tuple is
    returned with a position in the line, and a message. So to check the result
    just assertTrue if the check is expected to fail and assertFalse if it
    should pass.
    """
    def test_virt_driver_imports(self):

        expect = (0, "N311: importing code from other virt drivers forbidden")

        self.assertEqual(expect, checks.import_no_virt_driver_import_deps(
            "from nova.virt.libvirt import utils as libvirt_utils",
            "./nova/virt/xenapi/driver.py"))

        self.assertEqual(expect, checks.import_no_virt_driver_import_deps(
            "import nova.virt.libvirt.utils as libvirt_utils",
            "./nova/virt/xenapi/driver.py"))

        self.assertIsNone(checks.import_no_virt_driver_import_deps(
            "from nova.virt.libvirt import utils as libvirt_utils",
            "./nova/virt/libvirt/driver.py"))

        self.assertIsNone(checks.import_no_virt_driver_import_deps(
            "import nova.virt.firewall",
            "./nova/virt/libvirt/firewall.py"))

    def test_virt_driver_config_vars(self):
        self.assertIsInstance(checks.import_no_virt_driver_config_deps(
            "CONF.import_opt('volume_drivers', "
            "'nova.virt.libvirt.driver', group='libvirt')",
            "./nova/virt/xenapi/driver.py"), tuple)

        self.assertIsNone(checks.import_no_virt_driver_config_deps(
            "CONF.import_opt('volume_drivers', "
            "'nova.virt.libvirt.driver', group='libvirt')",
            "./nova/virt/libvirt/volume.py"))

    def test_no_author_tags(self):
        self.assertIsInstance(checks.no_author_tags("# author: jogo"), tuple)
        self.assertIsInstance(checks.no_author_tags("# @author: jogo"), tuple)
        self.assertIsInstance(checks.no_author_tags("# @Author: jogo"), tuple)
        self.assertIsInstance(checks.no_author_tags("# Author: jogo"), tuple)
        self.assertIsInstance(checks.no_author_tags(".. moduleauthor:: jogo"),
                              tuple)
        self.assertIsNone(checks.no_author_tags("# authorization of this"))
        self.assertEqual(2, checks.no_author_tags("# author: jogo")[0])
        self.assertEqual(2, checks.no_author_tags("# Author: jogo")[0])
        self.assertEqual(3, checks.no_author_tags(".. moduleauthor:: jogo")[0])

    def test_assert_true_instance(self):
        self.assertEqual(len(list(checks.assert_true_instance(
            "self.assertTrue(isinstance(e, "
            "exception.BuildAbortException))"))), 1)

        self.assertEqual(
            len(list(checks.assert_true_instance("self.assertTrue()"))), 0)

    def test_assert_equal_type(self):
        self.assertEqual(len(list(checks.assert_equal_type(
            "self.assertEqual(type(als['QuicAssist']), list)"))), 1)

        self.assertEqual(
            len(list(checks.assert_equal_type("self.assertTrue()"))), 0)

    def test_assert_equal_none(self):
        self.assertEqual(len(list(checks.assert_equal_none(
            "self.assertEqual(A, None)"))), 1)

        self.assertEqual(len(list(checks.assert_equal_none(
            "self.assertEqual(None, A)"))), 1)

        self.assertEqual(
            len(list(checks.assert_equal_none("self.assertIsNone()"))), 0)

    def test_no_translate_debug_logs(self):
        self.assertEqual(len(list(checks.no_translate_debug_logs(
            "LOG.debug(_('foo'))", "nova/scheduler/foo.py"))), 1)

        self.assertEqual(len(list(checks.no_translate_debug_logs(
            "LOG.debug('foo')", "nova/scheduler/foo.py"))), 0)

        self.assertEqual(len(list(checks.no_translate_debug_logs(
            "LOG.info(_('foo'))", "nova/scheduler/foo.py"))), 0)

    def test_no_setting_conf_directly_in_tests(self):
        self.assertEqual(len(list(checks.no_setting_conf_directly_in_tests(
            "CONF.option = 1", "nova/tests/test_foo.py"))), 1)

        self.assertEqual(len(list(checks.no_setting_conf_directly_in_tests(
            "CONF.group.option = 1", "nova/tests/test_foo.py"))), 1)

        self.assertEqual(len(list(checks.no_setting_conf_directly_in_tests(
            "CONF.option = foo = 1", "nova/tests/test_foo.py"))), 1)

        # Shouldn't fail with comparisons
        self.assertEqual(len(list(checks.no_setting_conf_directly_in_tests(
            "CONF.option == 'foo'", "nova/tests/test_foo.py"))), 0)

        self.assertEqual(len(list(checks.no_setting_conf_directly_in_tests(
            "CONF.option != 1", "nova/tests/test_foo.py"))), 0)

        # Shouldn't fail since not in nova/tests/
        self.assertEqual(len(list(checks.no_setting_conf_directly_in_tests(
            "CONF.option = 1", "nova/compute/foo.py"))), 0)

    def test_log_translations(self):
        logs = ['audit', 'error', 'info', 'warn', 'warning', 'critical',
                'exception']
        levels = ['_LI', '_LW', '_LE', '_LC']
        debug = "LOG.debug('OK')"
        self.assertEqual(0,
            len(list(
                checks.validate_log_translations(debug, debug, 'f'))))
        for log in logs:
            bad = 'LOG.%s("Bad")' % log
            self.assertEqual(1,
                len(list(
                    checks.validate_log_translations(bad, bad, 'f'))))
            ok = "LOG.%s(_('OK'))" % log
            self.assertEqual(0,
                len(list(
                    checks.validate_log_translations(ok, ok, 'f'))))
            ok = "LOG.%s('OK')    # noqa" % log
            self.assertEqual(0,
                len(list(
                    checks.validate_log_translations(ok, ok, 'f'))))
            ok = "LOG.%s(variable)" % log
            self.assertEqual(0,
                len(list(
                    checks.validate_log_translations(ok, ok, 'f'))))
            for level in levels:
                ok = "LOG.%s(%s('OK'))" % (log, level)
                self.assertEqual(0,
                    len(list(
                        checks.validate_log_translations(ok, ok, 'f'))))

    def test_no_mutable_default_args(self):
        self.assertEqual(1, len(list(checks.no_mutable_default_args(
            " def fake_suds_context(calls={}):"))))

        self.assertEqual(1, len(list(checks.no_mutable_default_args(
            "def get_info_from_bdm(virt_type, bdm, mapping=[])"))))

        self.assertEqual(0, len(list(checks.no_mutable_default_args(
            "defined = []"))))

        self.assertEqual(0, len(list(checks.no_mutable_default_args(
            "defined, undefined = [], {}"))))

    def test_check_explicit_underscore_import(self):
        self.assertEqual(len(list(checks.check_explicit_underscore_import(
            "LOG.info(_('My info message'))",
            "cinder/tests/other_files.py"))), 1)
        self.assertEqual(len(list(checks.check_explicit_underscore_import(
            "msg = _('My message')",
            "cinder/tests/other_files.py"))), 1)
        self.assertEqual(len(list(checks.check_explicit_underscore_import(
            "from cinder.i18n import _",
            "cinder/tests/other_files.py"))), 0)
        self.assertEqual(len(list(checks.check_explicit_underscore_import(
            "LOG.info(_('My info message'))",
            "cinder/tests/other_files.py"))), 0)
        self.assertEqual(len(list(checks.check_explicit_underscore_import(
            "msg = _('My message')",
            "cinder/tests/other_files.py"))), 0)
        self.assertEqual(len(list(checks.check_explicit_underscore_import(
            "from cinder.i18n import _, _LW",
            "cinder/tests/other_files2.py"))), 0)
        self.assertEqual(len(list(checks.check_explicit_underscore_import(
            "msg = _('My message')",
            "cinder/tests/other_files2.py"))), 0)
        self.assertEqual(len(list(checks.check_explicit_underscore_import(
            "_ = translations.ugettext",
            "cinder/tests/other_files3.py"))), 0)
        self.assertEqual(len(list(checks.check_explicit_underscore_import(
            "msg = _('My message')",
            "cinder/tests/other_files3.py"))), 0)

    def test_use_jsonutils(self):
        def __get_msg(fun):
            msg = ("N324: jsonutils.%(fun)s must be used instead of "
                   "json.%(fun)s" % {'fun': fun})
            return [(0, msg)]

        for method in ('dump', 'dumps', 'load', 'loads'):
            self.assertEqual(
                __get_msg(method),
                list(checks.use_jsonutils("json.%s(" % method,
                                     "./nova/virt/xenapi/driver.py")))
            self.assertEqual(0,
                len(list(checks.use_jsonutils("json.%s(" % method,
                                     "./plugins/xenserver/script.py"))))
            self.assertEqual(0,
                len(list(checks.use_jsonutils("jsonx.%s(" % method,
                                     "./nova/virt/xenapi/driver.py"))))
        self.assertEqual(0,
            len(list(checks.use_jsonutils("json.dumb",
                                 "./nova/virt/xenapi/driver.py"))))

    # We are patching pep8 so that only the check under test is actually
    # installed.
    @mock.patch('pep8._checks',
                {'physical_line': {}, 'logical_line': {}, 'tree': {}})
    def _run_check(self, code, checker, filename=None):
        pep8.register_check(checker)

        lines = textwrap.dedent(code).strip().splitlines(True)

        checker = pep8.Checker(filename=filename, lines=lines)
        checker.check_all()
        checker.report._deferred_print.sort()
        return checker.report._deferred_print

    def _assert_has_errors(self, code, checker, expected_errors=None,
                           filename=None):
        actual_errors = [e[:3] for e in
                         self._run_check(code, checker, filename)]
        self.assertEqual(expected_errors or [], actual_errors)

    def test_assert_called_once(self):

        checker = checks.check_assert_called_once
        code = """
               mock = Mock()
               mock.method(1, 2, 3, test='wow')
               mock.method.assert_called_once()
               """
        errors = [(3, 11, 'N327')]
        self._assert_has_errors(code, checker, expected_errors=errors,
                                filename='nova/tests/test_assert.py')

    def test_str_exception(self):

        checker = checks.CheckForStrExc
        code = """
               def f(a, b):
                   try:
                       p = str(a) + str(b)
                   except ValueError as e:
                       p = str(e)
                   return p
               """
        errors = [(5, 16, 'N325')]
        self._assert_has_errors(code, checker, expected_errors=errors)

        code = """
               def f(a, b):
                   try:
                       p = str(a) + str(b)
                   except ValueError as e:
                       p = unicode(e)
                   return p
               """
        errors = []
        self._assert_has_errors(code, checker, expected_errors=errors)

        code = """
               def f(a, b):
                   try:
                       p = str(a) + str(b)
                   except ValueError as e:
                       try:
                           p  = unicode(a) + unicode(b)
                       except ValueError as ve:
                           p = str(e) + str(ve)
                       p = unicode(e)
                   return p
               """
        errors = [(8, 20, 'N325'), (8, 29, 'N325')]
        self._assert_has_errors(code, checker, expected_errors=errors)

    def test_trans_add(self):

        checker = checks.CheckForTransAdd
        code = """
               def fake_tran(msg):
                   return msg


               _ = fake_tran
               _LI = _
               _LW = _
               _LE = _
               _LC = _


               def f(a, b):
                   msg = _('test') + 'add me'
                   msg = _LI('test') + 'add me'
                   msg = _LW('test') + 'add me'
                   msg = _LE('test') + 'add me'
                   msg = _LC('test') + 'add me'
                   msg = 'add to me' + _('test')
                   return msg
               """
        errors = [(13, 10, 'N326'), (14, 10, 'N326'), (15, 10, 'N326'),
                  (16, 10, 'N326'), (17, 10, 'N326'), (18, 24, 'N326')]
        self._assert_has_errors(code, checker, expected_errors=errors)

        code = """
               def f(a, b):
                   msg = 'test' + 'add me'
                   return msg
               """
        errors = []
        self._assert_has_errors(code, checker, expected_errors=errors)
