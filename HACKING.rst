Nova Style Commandments
=======================

- Step 1: Read the OpenStack Style Commandments
  http://docs.openstack.org/developer/hacking/
- Step 2: Read on

Nova Specific Commandments
---------------------------

- ``nova.db`` imports are not allowed in ``nova/virt/*``
- [N309] no db session in public API methods (disabled)
  This enforces a guideline defined in ``oslo.db.sqlalchemy.session``
- [N310] timeutils.utcnow() wrapper must be used instead of direct calls to
  datetime.datetime.utcnow() to make it easy to override its return value in tests
- [N311] importing code from other virt drivers forbidden
  Code that needs to be shared between virt drivers should be moved
  into a common module
- [N312] using config vars from other virt drivers forbidden
  Config parameters that need to be shared between virt drivers
  should be moved into a common module
- [N313] capitalize help string
  Config parameter help strings should have a capitalized first letter
- [N314] vim configuration should not be kept in source files.
- [N316] Change assertTrue(isinstance(A, B)) by optimal assert like
  assertIsInstance(A, B).
- [N317] Change assertEqual(type(A), B) by optimal assert like
  assertIsInstance(A, B)
- [N318] Change assertEqual(A, None) or assertEqual(None, A) by optimal assert like
  assertIsNone(A)
- [N319] Validate that debug level logs are not translated.
- [N320] Setting CONF.* attributes directly in tests is forbidden. Use
  self.flags(option=value) instead.
- [N321] Validate that LOG messages, except debug ones, have translations
- [N322] Method's default argument shouldn't be mutable
- [N323] Ensure that the _() function is explicitly imported to ensure proper translations.
- [N324] Ensure that jsonutils.%(fun)s must be used instead of json.%(fun)s
- [N325] str() and unicode() cannot be used on an exception.  Remove use or use six.text_type()
- [N326] Translated messages cannot be concatenated.  String should be included in translated message.
- [N328] Validate that LOG.info messages use _LI.
- [N329] Validate that LOG.exception messages use _LE.
- [N330] Validate that LOG.warning and LOG.warn messages use _LW.
- [N332] Check that the api_version decorator is the first decorator on a method
- [N333] Check for oslo library imports use the non-namespaced packages
- [N334] Change assertTrue/False(A in/not in B, message) to the more specific
  assertIn/NotIn(A, B, message)
- [N335] Check for usage of deprecated assertRaisesRegexp
- [N336] Must use a dict comprehension instead of a dict constructor with a sequence of key-value pairs.
- [N337] Don't import translation in tests
- [N338] Change assertEqual(A in B, True), assertEqual(True, A in B),
  assertEqual(A in B, False) or assertEqual(False, A in B) to the more specific
  assertIn/NotIn(A, B)

Creating Unit Tests
-------------------
For every new feature, unit tests should be created that both test and
(implicitly) document the usage of said feature. If submitting a patch for a
bug that had no unit test, a new passing unit test should be added. If a
submitted bug fix does have a unit test, be sure to add a new one that fails
without the patch and passes with the patch.

For more information on creating unit tests and utilizing the testing
infrastructure in OpenStack Nova, please read ``nova/tests/unit/README.rst``.


Running Tests
-------------
The testing system is based on a combination of tox and testr. The canonical
approach to running tests is to simply run the command ``tox``. This will
create virtual environments, populate them with dependencies and run all of
the tests that OpenStack CI systems run. Behind the scenes, tox is running
``testr run --parallel``, but is set up such that you can supply any additional
testr arguments that are needed to tox. For example, you can run:
``tox -- --analyze-isolation`` to cause tox to tell testr to add
--analyze-isolation to its argument list.

Python packages may also have dependencies that are outside of tox's ability
to install. Please refer to doc/source/devref/development.environment.rst for
a list of those packages on Ubuntu, Fedora and Mac OS X.

It is also possible to run the tests inside of a virtual environment
you have created, or it is possible that you have all of the dependencies
installed locally already. In this case, you can interact with the testr
command directly. Running ``testr run`` will run the entire test suite. ``testr
run --parallel`` will run it in parallel (this is the default incantation tox
uses.) More information about testr can be found at:
http://wiki.openstack.org/testr

Building Docs
-------------
Normal Sphinx docs can be built via the setuptools ``build_sphinx`` command. To
do this via ``tox``, simply run ``tox -evenv -- python setup.py build_sphinx``,
which will cause a virtualenv with all of the needed dependencies to be
created and then inside of the virtualenv, the docs will be created and
put into doc/build/html.

If you'd like a PDF of the documentation, you'll need LaTeX installed, and
additionally some fonts. On Ubuntu systems, you can get what you need with::

    apt-get install texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended

Then run ``build_sphinx_latex``, change to the build dir and run ``make``.
Like so::

    tox -evenv -- python setup.py build_sphinx_latex
    cd build/sphinx/latex
    make

You should wind up with a PDF - Nova.pdf.
