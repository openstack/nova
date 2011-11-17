Internationalization
====================
nova uses `gettext <http://docs.python.org/library/gettext.html>`_ so that
user-facing strings such as log messages appear in the appropriate
language in different locales.

To use gettext, make sure that the strings passed to the logger are wrapped
in a ``_()`` function call. For example::

    LOG.debug(_("block_device_mapping %s"), block_device_mapping)

If you have multiple arguments, the convention is to use named parameters.
It's common to use the ``locals()`` dict (which contains the names and values
of the local variables in the current scope) to do the string interpolation.
For example::

    label = ...
    sr_ref = ...
    LOG.debug(_('Introduced %(label)s as %(sr_ref)s.') % locals())

If you do not follow the project conventions, your code may cause the
LocalizationTestCase.test_multiple_positional_format_placeholders test to fail
in nova/tests/test_localization.py.

The ``_()`` function is brought into the global scope by doing::

    import gettext
    gettext.install("nova", unicode=1)

In general, you shouldn't need to add these to any nova files, since the lines
are present in ``nova/__init__.py``. However, if this code is missing, it may
result in an error that looks like like::

    NameError: name '_' is not defined
