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
import pycodestyle

from nova.hacking import checks
from nova import test


class HackingTestCase(test.NoDBTestCase):
    """This class tests the hacking checks in nova.hacking.checks by passing
    strings to the check methods like the pycodestyle/flake8 parser would. The
    parser loops over each line in the file and then passes the parameters to
    the check method. The parameter names in the check method dictate what type
    of object is passed to the check method. The parameter types are::

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
        filename: Path of the file being run through pycodestyle

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
            "./nova/virt/hyperv/driver.py"))

        self.assertEqual(expect, checks.import_no_virt_driver_import_deps(
            "import nova.virt.libvirt.utils as libvirt_utils",
            "./nova/virt/hyperv/driver.py"))

        self.assertIsNone(checks.import_no_virt_driver_import_deps(
            "from nova.virt.libvirt import utils as libvirt_utils",
            "./nova/virt/libvirt/driver.py"))

    def test_virt_driver_config_vars(self):
        self.assertIsInstance(checks.import_no_virt_driver_config_deps(
            "CONF.import_opt('volume_drivers', "
            "'nova.virt.libvirt.driver', group='libvirt')",
            "./nova/virt/hyperv/driver.py"), tuple)

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

    def test_no_translate_logs(self):
        self.assertEqual(len(list(checks.no_translate_logs(
            "LOG.debug(_('foo'))", "nova/scheduler/foo.py"))), 1)

        self.assertEqual(len(list(checks.no_translate_logs(
            "LOG.debug('foo')", "nova/scheduler/foo.py"))), 0)

        self.assertEqual(len(list(checks.no_translate_logs(
            "LOG.info(_('foo'))", "nova/scheduler/foo.py"))), 1)

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
            "msg = _('My message')",
            "cinder/tests/other_files.py"))), 1)
        self.assertEqual(len(list(checks.check_explicit_underscore_import(
            "from cinder.i18n import _",
            "cinder/tests/other_files.py"))), 0)
        self.assertEqual(len(list(checks.check_explicit_underscore_import(
            "msg = _('My message')",
            "cinder/tests/other_files.py"))), 0)
        self.assertEqual(len(list(checks.check_explicit_underscore_import(
            "from cinder.i18n import _",
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
                list(checks.use_jsonutils(
                    "json.%s(" % method, "./nova/virt/libvirt/driver.py")),
            )
            self.assertEqual(
                0,
                len(list(checks.use_jsonutils(
                    "jsonx.%s(" % method, "./nova/virt/libvirt/driver.py"))),
            )

        self.assertEqual(
            0,
            len(list(checks.use_jsonutils(
                "json.dumb", "./nova/virt/libvirt/driver.py"))),
        )

    # We are patching pycodestyle so that only the check under test is actually
    # installed.
    @mock.patch('pycodestyle._checks',
                {'physical_line': {}, 'logical_line': {}, 'tree': {}})
    def _run_check(self, code, checker, filename=None):
        pycodestyle.register_check(checker)

        lines = textwrap.dedent(code).lstrip().splitlines(True)

        checker = pycodestyle.Checker(filename=filename, lines=lines)
        # NOTE(sdague): the standard reporter has printing to stdout
        # as a normal part of check_all, which bleeds through to the
        # test output stream in an unhelpful way. This blocks that printing.
        with mock.patch('pycodestyle.StandardReport.get_file_results'):
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
        codelist = [
            """
            class ControllerClass():
                @wsgi.api_version("2.5")
                def my_method():
                    pass
            """,
            """
            @some_other_decorator
            @mock.patch('foo', return_value=api_versions.APIVersion("2.5"))
            def my_method():
                pass
            """]
        for code in codelist:
            self._assert_has_no_errors(
                code, checks.check_api_version_decorator)

    def test_trans_add(self):

        checker = checks.CheckForTransAdd
        code = """
               def fake_tran(msg):
                   return msg


               _ = fake_tran


               def f(a, b):
                   msg = _('test') + 'add me'
                   msg = 'add to me' + _('test')
                   return msg
               """
        errors = [(9, 10, 'N326'), (10, 24, 'N326')]
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

        # Explicit addition of line-ending here and below since this isn't a
        # block comment and without it we trigger #1804062. Artificial break is
        # necessary to stop flake8 detecting the test
        code = "'This is the" + " the best comment'\n"
        self._assert_has_errors(code, checks.check_doubled_words,
                                expected_errors=errors)

        code = "'This is the then best comment'\n"
        self._assert_has_no_errors(code, checks.check_doubled_words)

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

    def test_log_context(self):
        code = """
                  LOG.info("Rebooting instance",
                           context=context, instance=instance)
               """
        errors = [(1, 0, 'N353')]
        self._assert_has_errors(code, checks.check_context_log,
                                expected_errors=errors)
        code = """
                  LOG.info("Rebooting instance",
                           context=admin_context, instance=instance)
               """
        errors = [(1, 0, 'N353')]
        self._assert_has_errors(code, checks.check_context_log,
                                expected_errors=errors)
        code = """
                  LOG.info("Rebooting instance", instance=instance)
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
        code = """
                  return(42)
                  return(a, b)
                  return(' some string ')
               """
        errors = [(1, 0, 'N358'), (2, 0, 'N358'), (3, 0, 'N358')]
        self._assert_has_errors(code, checks.return_followed_by_space,
                                expected_errors=errors)
        code = """
                  return
                  return 42
                  return (a, b)
                  return a, b
                  return ' some string '
               """
        self._assert_has_no_errors(code, checks.return_followed_by_space)

    def test_no_redundant_import_alias(self):
        code = """
                  from x import y as y
                  import x as x
                  import x.y.z as z
                  import x.y.z as y.z
               """
        errors = [(x + 1, 0, 'N359') for x in range(4)]
        self._assert_has_errors(code, checks.no_redundant_import_alias,
                                expected_errors=errors)
        code = """
                  from x import y
                  import x
                  from x.y import z
                  from a import bcd as cd
                  import ab.cd.efg as fg
                  import ab.cd.efg as d.efg
               """
        self._assert_has_no_errors(code, checks.no_redundant_import_alias)

    def test_yield_followed_by_space(self):
        code = """
                  yield(x, y)
                  yield{"type": "test"}
                  yield[a, b, c]
                  yield"test"
                  yield'test'
               """
        errors = [(x + 1, 0, 'N360') for x in range(5)]
        self._assert_has_errors(code, checks.yield_followed_by_space,
                                expected_errors=errors)
        code = """
                  yield x
                  yield (x, y)
                  yield {"type": "test"}
                  yield [a, b, c]
                  yield "test"
                  yield 'test'
                  yieldx_func(a, b)
               """
        self._assert_has_no_errors(code, checks.yield_followed_by_space)

    def test_assert_regexpmatches(self):
        code = """
                   self.assertRegexpMatches("Test", output)
                   self.assertNotRegexpMatches("Notmatch", output)
               """
        errors = [(x + 1, 0, 'N361') for x in range(2)]
        self._assert_has_errors(code, checks.assert_regexpmatches,
                                expected_errors=errors)
        code = """
                   self.assertRegexpMatchesfoo("Test", output)
                   self.assertNotRegexpMatchesbar("Notmatch", output)
               """
        self._assert_has_no_errors(code, checks.assert_regexpmatches)

    def test_import_alias_privsep(self):
        code = """
                  from nova import privsep
                  import nova.privsep as nova_privsep
                  from nova.privsep import linux_net
                  import nova.privsep.linux_net as privsep_linux_net
               """
        errors = [(x + 1, 0, 'N362') for x in range(4)]
        bad_filenames = ('nova/foo/bar.py',
                         'nova/foo/privsep.py',
                         'nova/privsep_foo/bar.py')
        for filename in bad_filenames:
            self._assert_has_errors(
                code, checks.privsep_imports_not_aliased,
                expected_errors=errors,
                filename=filename)
        good_filenames = ('nova/privsep.py',
                          'nova/privsep/__init__.py',
                          'nova/privsep/foo.py')
        for filename in good_filenames:
            self._assert_has_no_errors(
                code, checks.privsep_imports_not_aliased, filename=filename)
        code = """
                  import nova.privsep
                  import nova.privsep.foo
                  import nova.privsep.foo.bar
                  import nova.foo.privsep
                  import nova.foo.privsep.bar
                  import nova.tests.unit.whatever
               """
        for filename in (good_filenames + bad_filenames):
            self._assert_has_no_errors(
                code, checks.privsep_imports_not_aliased, filename=filename)

    def test_did_you_mean_tuple(self):
        code = """
                    if foo in (bar):
                    if foo in ('bar'):
                    if foo in (path.to.CONST_1234):
                    if foo in (
                        bar):
               """
        errors = [(x + 1, 0, 'N363') for x in range(4)]
        self._assert_has_errors(
            code, checks.did_you_mean_tuple, expected_errors=errors)
        code = """
                    def in(this_would_be_weird):
                        # A match in (any) comment doesn't count
                        if foo in (bar,)
                            or foo in ('bar',)
                            or foo in ("bar",)
                            or foo in (set1 + set2)
                            or foo in ("string continuations "
                                "are probably okay")
                            or foo in (method_call_should_this_work()):
               """
        self._assert_has_no_errors(code, checks.did_you_mean_tuple)

    def test_nonexistent_assertion_methods_and_attributes(self):
        code = """
                   mock_sample.called_once()
                   mock_sample.called_once_with(a, "TEST")
                   mock_sample.has_calls([mock.call(x), mock.call(y)])
                   mock_sample.mock_assert_called()
                   mock_sample.mock_assert_called_once()
                   mock_sample.mock_assert_called_with(a, "xxxx")
                   mock_sample.mock_assert_called_once_with(a, b)
                   mock_sample.mock_assert_any_call(1, 2, instance=instance)
                   sample.mock_assert_has_calls([mock.call(x), mock.call(y)])
                   mock_sample.mock_assert_not_called()
                   mock_sample.asser_called()
                   mock_sample.asser_called_once()
                   mock_sample.asser_called_with(a, "xxxx")
                   mock_sample.asser_called_once_with(a, b)
                   mock_sample.asser_any_call(1, 2, instance=instance)
                   mock_sample.asser_has_calls([mock.call(x), mock.call(y)])
                   mock_sample.asser_not_called()
                   mock_sample.asset_called()
                   mock_sample.asset_called_once()
                   mock_sample.asset_called_with(a, "xxxx")
                   mock_sample.asset_called_once_with(a, b)
                   mock_sample.asset_any_call(1, 2, instance=instance)
                   mock_sample.asset_has_calls([mock.call(x), mock.call(y)])
                   mock_sample.asset_not_called()
                   mock_sample.asssert_called()
                   mock_sample.asssert_called_once()
                   mock_sample.asssert_called_with(a, "xxxx")
                   mock_sample.asssert_called_once_with(a, b)
                   mock_sample.asssert_any_call(1, 2, instance=instance)
                   mock_sample.asssert_has_calls([mock.call(x), mock.call(y)])
                   mock_sample.asssert_not_called()
                   mock_sample.assset_called()
                   mock_sample.assset_called_once()
                   mock_sample.assset_called_with(a, "xxxx")
                   mock_sample.assset_called_once_with(a, b)
                   mock_sample.assset_any_call(1, 2, instance=instance)
                   mock_sample.assset_has_calls([mock.call(x), mock.call(y)])
                   mock_sample.assset_not_called()
                   mock_sample.retrun_value = 100
                   sample.call_method(mock_sample.retrun_value, 100)
                   mock.Mock(retrun_value=100)
               """
        errors = [(x + 1, 0, 'N364') for x in range(41)]
        # Check errors in 'nova/tests' directory.
        self._assert_has_errors(
            code, checks.nonexistent_assertion_methods_and_attributes,
            expected_errors=errors, filename="nova/tests/unit/test_context.py")
        # Check no errors in other than 'nova/tests' directory.
        self._assert_has_no_errors(
            code, checks.nonexistent_assertion_methods_and_attributes,
            filename="nova/compute/api.py")

        code = """
                   mock_sample.assert_called()
                   mock_sample.assert_called_once()
                   mock_sample.assert_called_with(a, "xxxx")
                   mock_sample.assert_called_once_with(a, b)
                   mock_sample.assert_any_call(1, 2, instance=instance)
                   mock_sample.assert_has_calls([mock.call(x), mock.call(y)])
                   mock_sample.assert_not_called()
                   mock_sample.return_value = 100
                   sample.call_method(mock_sample.return_value, 100)
                   mock.Mock(return_value=100)

                   sample.has_other_calls([1, 2, 3, 4])
                   sample.get_called_once("TEST")
                   sample.check_called_once_with("TEST")
                   mock_assert_method.assert_called()
                   test.asset_has_all(test)
                   test_retrun_value = 99
                   test.retrun_values = 100
               """
        self._assert_has_no_errors(
            code, checks.nonexistent_assertion_methods_and_attributes,
            filename="nova/tests/unit/test_context.py")

    def test_useless_assertion(self):
        code = """
                   self.assertIsNone(None, status)
                   self.assertTrue(True, flag)
                   self.assertTrue(10, count)
                   self.assertTrue('active', status)
                   self.assertTrue("building", status)
               """
        errors = [(x + 1, 0, 'N365') for x in range(5)]
        # Check errors in 'nova/tests' directory.
        self._assert_has_errors(
            code, checks.useless_assertion,
            expected_errors=errors, filename="nova/tests/unit/test_context.py")
        # Check no errors in other than 'nova/tests' directory.
        self._assert_has_no_errors(
            code, checks.useless_assertion,
            filename="nova/compute/api.py")
        code = """
                   self.assertIsNone(None_test_var, "Fails")
                   self.assertTrue(True_test_var, 'Fails')
                   self.assertTrue(var2, "Fails")
                   self.assertTrue(test_class.is_active('active'), 'Fails')
                   self.assertTrue(check_status("building"), 'Fails')
               """
        self._assert_has_no_errors(
            code, checks.useless_assertion,
            filename="nova/tests/unit/test_context.py")
