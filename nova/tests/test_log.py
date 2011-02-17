import cStringIO

from nova import context
from nova import log
from nova import test


def _fake_context():
    return context.RequestContext(1, 1)


class RootLoggerTestCase(test.TestCase):
    def setUp(self):
        super(RootLoggerTestCase, self).setUp()
        self.log = log.logging.root

    def tearDown(self):
        super(RootLoggerTestCase, self).tearDown()
        log.NovaLogger.manager.loggerDict = {}

    def test_is_nova_instance(self):
        self.assert_(isinstance(self.log, log.NovaLogger))

    def test_name_is_nova_root(self):
        self.assertEqual("nova.root", self.log.name)

    def test_handlers_have_nova_formatter(self):
        formatters = []
        for h in self.log.handlers:
            f = h.formatter
            if isinstance(f, log.NovaFormatter):
                formatters.append(f)
        self.assert_(formatters)
        self.assertEqual(len(formatters), len(self.log.handlers))

    def test_handles_context_kwarg(self):
        self.log.info("foo", context=_fake_context())
        self.assert_(True)  # didn't raise exception

    def test_module_level_methods_handle_context_arg(self):
        log.info("foo", context=_fake_context())
        self.assert_(True)  # didn't raise exception

    def test_module_level_audit_handles_context_arg(self):
        log.audit("foo", context=_fake_context())
        self.assert_(True)  # didn't raise exception


class LogHandlerTestCase(test.TestCase):
    def test_log_path_logdir(self):
        self.flags(logdir='/some/path')
        self.assertEquals(log.get_log_file_path(binary='foo-bar'),
                         '/some/path/foo-bar.log')

    def test_log_path_logfile(self):
        self.flags(logfile='/some/path/foo-bar.log')
        self.assertEquals(log.get_log_file_path(binary='foo-bar'),
                         '/some/path/foo-bar.log')

    def test_log_path_none(self):
        self.assertTrue(log.get_log_file_path(binary='foo-bar') is None)

    def test_log_path_logfile_overrides_logdir(self):
        self.flags(logdir='/some/other/path',
                   logfile='/some/path/foo-bar.log')
        self.assertEquals(log.get_log_file_path(binary='foo-bar'),
                         '/some/path/foo-bar.log')


class NovaFormatterTestCase(test.TestCase):
    def setUp(self):
        super(NovaFormatterTestCase, self).setUp()
        self.flags(logging_context_format_string="HAS CONTEXT "\
                                              "[%(request_id)s]: %(message)s",
                   logging_default_format_string="NOCTXT: %(message)s",
                   logging_debug_format_suffix="--DBG")
        self.log = log.logging.root
        self.stream = cStringIO.StringIO()
        handler = log.StreamHandler(self.stream)
        self.log.addHandler(handler)
        self.log.setLevel(log.DEBUG)

    def tearDown(self):
        super(NovaFormatterTestCase, self).tearDown()
        log.NovaLogger.manager.loggerDict = {}

    def test_uncontextualized_log(self):
        self.log.info("foo")
        self.assertEqual("NOCTXT: foo\n", self.stream.getvalue())

    def test_contextualized_log(self):
        ctxt = _fake_context()
        self.log.info("bar", context=ctxt)
        expected = "HAS CONTEXT [%s]: bar\n" % ctxt.request_id
        self.assertEqual(expected, self.stream.getvalue())

    def test_debugging_log(self):
        self.log.debug("baz")
        self.assertEqual("NOCTXT: baz --DBG\n", self.stream.getvalue())


class NovaLoggerTestCase(test.TestCase):
    def setUp(self):
        super(NovaLoggerTestCase, self).setUp()
        self.flags(default_log_levels=["nova-test=AUDIT"], verbose=False)
        self.log = log.getLogger('nova-test')

    def tearDown(self):
        super(NovaLoggerTestCase, self).tearDown()
        log.NovaLogger.manager.loggerDict = {}

    def test_has_level_from_flags(self):
        self.assertEqual(log.AUDIT, self.log.level)

    def test_child_log_has_level_of_parent_flag(self):
        l = log.getLogger('nova-test.foo')
        self.assertEqual(log.AUDIT, l.level)


class VerboseLoggerTestCase(test.TestCase):
    def setUp(self):
        super(VerboseLoggerTestCase, self).setUp()
        self.flags(default_log_levels=["nova.test=AUDIT"], verbose=True)
        self.log = log.getLogger('nova.test')

    def tearDown(self):
        super(VerboseLoggerTestCase, self).tearDown()
        log.NovaLogger.manager.loggerDict = {}

    def test_will_be_verbose_if_named_nova_and_verbose_flag_set(self):
        self.assertEqual(log.DEBUG, self.log.level)
