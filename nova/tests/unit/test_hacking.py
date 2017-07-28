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

    def test_assert_equal_in(self):
        self.assertEqual(len(list(checks.assert_equal_in(
            "self.assertEqual(a in b, True)"))), 1)

        self.assertEqual(len(list(checks.assert_equal_in(
            "self.assertEqual('str' in 'string', True)"))), 1)

        self.assertEqual(len(list(checks.assert_equal_in(
            "self.assertEqual(any(a==1 for a in b), True)"))), 0)

        self.assertEqual(len(list(checks.assert_equal_in(
            "self.assertEqual(True, a in b)"))), 1)

        self.assertEqual(len(list(checks.assert_equal_in(
            "self.assertEqual(True, 'str' in 'string')"))), 1)

        self.assertEqual(len(list(checks.assert_equal_in(
            "self.assertEqual(True, any(a==1 for a in b))"))), 0)

        self.assertEqual(len(list(checks.assert_equal_in(
            "self.assertEqual(a in b, False)"))), 1)

        self.assertEqual(len(list(checks.assert_equal_in(
            "self.assertEqual('str' in 'string', False)"))), 1)

        self.assertEqual(len(list(checks.assert_equal_in(
            "self.assertEqual(any(a==1 for a in b), False)"))), 0)

        self.assertEqual(len(list(checks.assert_equal_in(
            "self.assertEqual(False, a in b)"))), 1)

        self.assertEqual(len(list(checks.assert_equal_in(
            "self.assertEqual(False, 'str' in 'string')"))), 1)

        self.assertEqual(len(list(checks.assert_equal_in(
            "self.assertEqual(False, any(a==1 for a in b))"))), 0)

    def test_assert_true_or_false_with_in_or_not_in(self):
        self.assertEqual(len(list(checks.assert_true_or_false_with_in(
            "self.assertTrue(A in B)"))), 1)

        self.assertEqual(len(list(checks.assert_true_or_false_with_in(
            "self.assertFalse(A in B)"))), 1)

        self.assertEqual(len(list(checks.assert_true_or_false_with_in(
            "self.assertTrue(A not in B)"))), 1)

        self.assertEqual(len(list(checks.assert_true_or_false_with_in(
            "self.assertFalse(A not in B)"))), 1)

        self.assertEqual(len(list(checks.assert_true_or_false_with_in(
            "self.assertTrue(A in B, 'some message')"))), 1)

        self.assertEqual(len(list(checks.assert_true_or_false_with_in(
            "self.assertFalse(A in B, 'some message')"))), 1)

        self.assertEqual(len(list(checks.assert_true_or_false_with_in(
            "self.assertTrue(A not in B, 'some message')"))), 1)

        self.assertEqual(len(list(checks.assert_true_or_false_with_in(
            "self.assertFalse(A not in B, 'some message')"))), 1)

        self.assertEqual(len(list(checks.assert_true_or_false_with_in(
            "self.assertTrue(A in 'some string with spaces')"))), 1)

        self.assertEqual(len(list(checks.assert_true_or_false_with_in(
            "self.assertTrue(A in ['1', '2', '3'])"))), 1)

        self.assertEqual(len(list(checks.assert_true_or_false_with_in(
            "self.assertTrue(A in [1, 2, 3])"))), 1)

        self.assertEqual(len(list(checks.assert_true_or_false_with_in(
            "self.assertTrue(any(A > 5 for A in B))"))), 0)

        self.assertEqual(len(list(checks.assert_true_or_false_with_in(
            "self.assertTrue(any(A > 5 for A in B), 'some message')"))), 0)

        self.assertEqual(len(list(checks.assert_true_or_false_with_in(
            "self.assertFalse(some in list1 and some2 in list2)"))), 0)

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

    def test_no_mutable_default_args(self):
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
        # NOTE(sdague): the standard reporter has printing to stdout
        # as a normal part of check_all, which bleeds through to the
        # test output stream in an unhelpful way. This blocks that printing.
        with mock.patch('pep8.StandardReport.get_file_results'):
            checker.check_all()
        checker.report._deferred_print.sort()
        return checker.report._deferred_print

    def _assert_has_errors(self, code, checker, expected_errors=None,
                           filename=None):
        actual_errors = [e[:3] for e in
                         self._run_check(code, checker, filename)]
        self.assertEqual(expected_errors or [], actual_errors)

    def _assert_has_no_errors(self, code, checker, filename=None):
        self._assert_has_errors(code, checker, filename=filename)

    def test_str_unicode_exception(self):

        checker = checks.CheckForStrUnicodeExc
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
                       p = unicode(a) + str(b)
                   except ValueError as e:
                       p = e
                   return p
               """
        self._assert_has_no_errors(code, checker)

        code = """
               def f(a, b):
                   try:
                       p = str(a) + str(b)
                   except ValueError as e:
                       p = unicode(e)
                   return p
               """
        errors = [(5, 20, 'N325')]
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
                       p = e
                   return p
               """
        errors = [(8, 20, 'N325'), (8, 29, 'N325')]
        self._assert_has_errors(code, checker, expected_errors=errors)

        code = """
               def f(a, b):
                   try:
                       p = str(a) + str(b)
                   except ValueError as e:
                       try:
                           p  = unicode(a) + unicode(b)
                       except ValueError as ve:
                           p = str(e) + unicode(ve)
                       p = str(e)
                   return p
               """
        errors = [(8, 20, 'N325'), (8, 33, 'N325'), (9, 16, 'N325')]
        self._assert_has_errors(code, checker, expected_errors=errors)

    def test_api_version_decorator_check(self):
        code = """
               @some_other_decorator
               @wsgi.api_version("2.5")
               def my_method():
                   pass
               """
        self._assert_has_errors(code, checks.check_api_version_decorator,
                                expected_errors=[(2, 0, "N332")])

    def test_oslo_assert_raises_regexp(self):
        code = """
               self.assertRaisesRegexp(ValueError,
                                       "invalid literal for.*XYZ'$",
                                       int,
                                       'XYZ')
               """
        self._assert_has_errors(code, checks.assert_raises_regexp,
                                expected_errors=[(1, 0, "N335")])

    def test_api_version_decorator_check_no_errors(self):
        code = """
               class ControllerClass():
                   @wsgi.api_version("2.5")
                   def my_method():
                       pass
               """
        self._assert_has_no_errors(code, checks.check_api_version_decorator)

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
        self._assert_has_no_errors(code, checker)

    def test_dict_constructor_with_list_copy(self):
        self.assertEqual(1, len(list(checks.dict_constructor_with_list_copy(
            "    dict([(i, connect_info[i])"))))

        self.assertEqual(1, len(list(checks.dict_constructor_with_list_copy(
            "    attrs = dict([(k, _from_json(v))"))))

        self.assertEqual(1, len(list(checks.dict_constructor_with_list_copy(
            "        type_names = dict((value, key) for key, value in"))))

        self.assertEqual(1, len(list(checks.dict_constructor_with_list_copy(
            "   dict((value, key) for key, value in"))))

        self.assertEqual(1, len(list(checks.dict_constructor_with_list_copy(
            "foo(param=dict((k, v) for k, v in bar.items()))"))))

        self.assertEqual(1, len(list(checks.dict_constructor_with_list_copy(
            " dict([[i,i] for i in range(3)])"))))

        self.assertEqual(1, len(list(checks.dict_constructor_with_list_copy(
            "  dd = dict([i,i] for i in range(3))"))))

        self.assertEqual(0, len(list(checks.dict_constructor_with_list_copy(
            "        create_kwargs = dict(snapshot=snapshot,"))))

        self.assertEqual(0, len(list(checks.dict_constructor_with_list_copy(
            "      self._render_dict(xml, data_el, data.__dict__)"))))

    def test_check_http_not_implemented(self):
        code = """
               except NotImplementedError:
                   common.raise_http_not_implemented_error()
               """
        filename = "nova/api/openstack/compute/v21/test.py"
        self._assert_has_no_errors(code, checks.check_http_not_implemented,
                                   filename=filename)

        code = """
               except NotImplementedError:
                   msg = _("Unable to set password on instance")
                   raise exc.HTTPNotImplemented(explanation=msg)
               """
        errors = [(3, 4, 'N339')]
        self._assert_has_errors(code, checks.check_http_not_implemented,
                                expected_errors=errors, filename=filename)

    def test_check_contextlib_use(self):
        code = """
               with test.nested(
                   mock.patch.object(network_model.NetworkInfo, 'hydrate'),
                   mock.patch.object(objects.InstanceInfoCache, 'save'),
               ) as (
                   hydrate_mock, save_mock
               )
               """
        filename = "nova/api/openstack/compute/v21/test.py"
        self._assert_has_no_errors(code, checks.check_no_contextlib_nested,
                                   filename=filename)
        code = """
               with contextlib.nested(
                   mock.patch.object(network_model.NetworkInfo, 'hydrate'),
                   mock.patch.object(objects.InstanceInfoCache, 'save'),
               ) as (
                   hydrate_mock, save_mock
               )
               """
        filename = "nova/api/openstack/compute/legacy_v2/test.py"
        errors = [(1, 0, 'N341')]
        self._assert_has_errors(code, checks.check_no_contextlib_nested,
                                expected_errors=errors, filename=filename)

    def test_check_greenthread_spawns(self):
        errors = [(1, 0, "N340")]

        code = "greenthread.spawn(func, arg1, kwarg1=kwarg1)"
        self._assert_has_errors(code, checks.check_greenthread_spawns,
                                expected_errors=errors)

        code = "greenthread.spawn_n(func, arg1, kwarg1=kwarg1)"
        self._assert_has_errors(code, checks.check_greenthread_spawns,
                                expected_errors=errors)

        code = "eventlet.greenthread.spawn(func, arg1, kwarg1=kwarg1)"
        self._assert_has_errors(code, checks.check_greenthread_spawns,
                                expected_errors=errors)

        code = "eventlet.spawn(func, arg1, kwarg1=kwarg1)"
        self._assert_has_errors(code, checks.check_greenthread_spawns,
                                expected_errors=errors)

        code = "eventlet.spawn_n(func, arg1, kwarg1=kwarg1)"
        self._assert_has_errors(code, checks.check_greenthread_spawns,
                                expected_errors=errors)

        code = "nova.utils.spawn(func, arg1, kwarg1=kwarg1)"
        self._assert_has_no_errors(code, checks.check_greenthread_spawns)

        code = "nova.utils.spawn_n(func, arg1, kwarg1=kwarg1)"
        self._assert_has_no_errors(code, checks.check_greenthread_spawns)

    def test_config_option_regex_match(self):
        def should_match(code):
            self.assertTrue(checks.cfg_opt_re.match(code))

        def should_not_match(code):
            self.assertFalse(checks.cfg_opt_re.match(code))

        should_match("opt = cfg.StrOpt('opt_name')")
        should_match("opt = cfg.IntOpt('opt_name')")
        should_match("opt = cfg.DictOpt('opt_name')")
        should_match("opt = cfg.Opt('opt_name')")
        should_match("opts=[cfg.Opt('opt_name')]")
        should_match("   cfg.Opt('opt_name')")
        should_not_match("opt_group = cfg.OptGroup('opt_group_name')")

    def test_check_config_option_in_central_place(self):
        errors = [(1, 0, "N342")]
        code = """
        opts = [
            cfg.StrOpt('random_opt',
                       default='foo',
                       help='I am here to do stuff'),
            ]
        """
        # option at the right place in the tree
        self._assert_has_no_errors(code,
                                   checks.check_config_option_in_central_place,
                                   filename="nova/conf/serial_console.py")
        # option at the wrong place in the tree
        self._assert_has_errors(code,
                                checks.check_config_option_in_central_place,
                                filename="nova/cmd/serialproxy.py",
                                expected_errors=errors)

        # option at a location which is marked as an exception
        # TODO(macsz) remove testing exceptions as they are removed from
        # check_config_option_in_central_place
        self._assert_has_no_errors(code,
                                   checks.check_config_option_in_central_place,
                                   filename="nova/cmd/manage.py")
        self._assert_has_no_errors(code,
                                   checks.check_config_option_in_central_place,
                                   filename="nova/tests/dummy_test.py")

    def test_check_doubled_words(self):
        errors = [(1, 0, "N343")]

        # Artificial break to stop pep8 detecting the test !
        code = "This is the" + " the best comment"
        self._assert_has_errors(code, checks.check_doubled_words,
                                expected_errors=errors)

        code = "This is the then best comment"
        self._assert_has_no_errors(code, checks.check_doubled_words)

    def test_dict_iteritems(self):
        self.assertEqual(1, len(list(checks.check_python3_no_iteritems(
            "obj.iteritems()"))))

        self.assertEqual(0, len(list(checks.check_python3_no_iteritems(
            "six.iteritems(ob))"))))

    def test_dict_iterkeys(self):
        self.assertEqual(1, len(list(checks.check_python3_no_iterkeys(
            "obj.iterkeys()"))))

        self.assertEqual(0, len(list(checks.check_python3_no_iterkeys(
            "six.iterkeys(ob))"))))

    def test_dict_itervalues(self):
        self.assertEqual(1, len(list(checks.check_python3_no_itervalues(
            "obj.itervalues()"))))

        self.assertEqual(0, len(list(checks.check_python3_no_itervalues(
            "six.itervalues(ob))"))))

    def test_no_os_popen(self):
        code = """
               import os

               foobar_cmd = "foobar -get -beer"
               answer = os.popen(foobar_cmd).read()

               if answer == nok":
                   try:
                       os.popen(os.popen('foobar -beer -please')).read()

                   except ValueError:
                       go_home()
               """
        errors = [(4, 0, 'N348'), (8, 8, 'N348')]
        self._assert_has_errors(code, checks.no_os_popen,
                                expected_errors=errors)

    def test_no_log_warn(self):
        code = """
                  LOG.warn("LOG.warn is deprecated")
               """
        errors = [(1, 0, 'N352')]
        self._assert_has_errors(code, checks.no_log_warn,
                                expected_errors=errors)
        code = """
                  LOG.warning("LOG.warn is deprecated")
               """
        self._assert_has_no_errors(code, checks.no_log_warn)

    def test_uncalled_closures(self):

        checker = checks.CheckForUncalledTestClosure
        code = """
               def test_fake_thing():
                   def _test():
                       pass
               """
        self._assert_has_errors(code, checker,
                expected_errors=[(1, 0, 'N349')])

        code = """
               def test_fake_thing():
                   def _test():
                       pass
                   _test()
               """
        self._assert_has_no_errors(code, checker)

        code = """
               def test_fake_thing():
                   def _test():
                       pass
                   self.assertRaises(FakeExcepion, _test)
               """
        self._assert_has_no_errors(code, checker)

    def test_check_policy_registration_in_central_place(self):
        errors = [(3, 0, "N350")]
        code = """
        from nova import policy

        policy.RuleDefault('context_is_admin', 'role:admin')
        """
        # registration in the proper place
        self._assert_has_no_errors(
            code, checks.check_policy_registration_in_central_place,
            filename="nova/policies/base.py")
        # option at a location which is not in scope right now
        self._assert_has_errors(
            code, checks.check_policy_registration_in_central_place,
            filename="nova/api/openstack/compute/non_existent.py",
            expected_errors=errors)

    def test_check_policy_enforce(self):
        errors = [(3, 0, "N351")]
        code = """
        from nova import policy

        policy._ENFORCER.enforce('context_is_admin', target, credentials)
        """
        self._assert_has_errors(code, checks.check_policy_enforce,
                                expected_errors=errors)

    def test_check_policy_enforce_does_not_catch_other_enforce(self):
        # Simulate a different enforce method defined in Nova
        code = """
        from nova import foo

        foo.enforce()
        """
        self._assert_has_no_errors(code, checks.check_policy_enforce)

    def test_check_python3_xrange(self):
        func = checks.check_python3_xrange
        self.assertEqual(1, len(list(func('for i in xrange(10)'))))
        self.assertEqual(1, len(list(func('for i in xrange    (10)'))))
        self.assertEqual(0, len(list(func('for i in range(10)'))))
        self.assertEqual(0, len(list(func('for i in six.moves.range(10)'))))

    def test_log_context(self):
        code = """
                  LOG.info(_LI("Rebooting instance"),
                            context=context, instance=instance)
               """
        errors = [(1, 0, 'N353')]
        self._assert_has_errors(code, checks.check_context_log,
                                expected_errors=errors)
        code = """
                  LOG.info(_LI("Rebooting instance"),
                            context=admin_context, instance=instance)
               """
        errors = [(1, 0, 'N353')]
        self._assert_has_errors(code, checks.check_context_log,
                                expected_errors=errors)
        code = """
                  LOG.info(_LI("Rebooting instance"),
                            instance=instance)
               """
        self._assert_has_no_errors(code, checks.check_context_log)

    def test_no_assert_equal_true_false(self):
        code = """
                  self.assertEqual(context_is_admin, True)
                  self.assertEqual(context_is_admin, False)
                  self.assertEqual(True, context_is_admin)
                  self.assertEqual(False, context_is_admin)
                  self.assertNotEqual(context_is_admin, True)
                  self.assertNotEqual(context_is_admin, False)
                  self.assertNotEqual(True, context_is_admin)
                  self.assertNotEqual(False, context_is_admin)
               """
        errors = [(1, 0, 'N355'), (2, 0, 'N355'), (3, 0, 'N355'),
                  (4, 0, 'N355'), (5, 0, 'N355'), (6, 0, 'N355'),
                  (7, 0, 'N355'), (8, 0, 'N355')]
        self._assert_has_errors(code, checks.no_assert_equal_true_false,
                                expected_errors=errors)
        code = """
                  self.assertEqual(context_is_admin, stuff)
                  self.assertNotEqual(context_is_admin, stuff)
               """
        self._assert_has_no_errors(code, checks.no_assert_equal_true_false)

    def test_no_assert_true_false_is_not(self):
        code = """
                  self.assertTrue(test is None)
                  self.assertTrue(False is my_variable)
                  self.assertFalse(None is test)
                  self.assertFalse(my_variable is False)
               """
        errors = [(1, 0, 'N356'), (2, 0, 'N356'), (3, 0, 'N356'),
                  (4, 0, 'N356')]
        self._assert_has_errors(code, checks.no_assert_true_false_is_not,
                                expected_errors=errors)

    def test_check_uuid4(self):
        code = """
                  fake_uuid = uuid.uuid4()
                  hex_uuid = uuid.uuid4().hex
               """
        errors = [(1, 0, 'N357'), (2, 0, 'N357')]
        self._assert_has_errors(code, checks.check_uuid4,
                                expected_errors=errors)
        code = """
                  int_uuid = uuid.uuid4().int
                  urn_uuid = uuid.uuid4().urn
                  variant_uuid = uuid.uuid4().variant
                  version_uuid = uuid.uuid4().version
               """
        self._assert_has_no_errors(code, checks.check_uuid4)

    def test_return_followed_by_space(self):
        self.assertEqual(1, len(list(checks.return_followed_by_space(
            "return(42)"))))
        self.assertEqual(1, len(list(checks.return_followed_by_space(
            "return(' some string ')"))))
        self.assertEqual(0, len(list(checks.return_followed_by_space(
            "return 42"))))
        self.assertEqual(0, len(list(checks.return_followed_by_space(
            "return ' some string '"))))
        self.assertEqual(0, len(list(checks.return_followed_by_space(
            "return (int('40') + 2)"))))
