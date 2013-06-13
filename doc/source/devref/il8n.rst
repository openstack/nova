Internationalization
====================
nova uses `gettext <http://docs.python.org/library/gettext.html>`_ so that
user-facing strings such as log messages appear in the appropriate
language in different locales.

To use gettext, make sure that the strings passed to the logger are wrapped
in a ``_()`` function call. For example::

    LOG.debug(_("block_device_mapping %s"), block_device_mapping)

Do not use ``locals()`` for formatting messages because:
1. It is not as clear as using explicit dicts.
2. It could produce hidden errors during refactoring.
3. Changing the name of a variable causes a change in the message.
4. It creates a lot of otherwise unused variables.

If you do not follow the project conventions, your code may cause the
LocalizationTestCase.test_multiple_positional_format_placeholders test to fail
in nova/tests/test_localization.py.

The ``_()`` function is found by doing::

    from nova.openstack.common.gettextutils import _
