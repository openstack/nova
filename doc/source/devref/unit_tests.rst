Unit Tests
==========

Nova contains a suite of unit tests, in the nova/tests directory.

Any proposed code change will be automatically rejected by the OpenStack
Jenkins server [#f1]_ if the change causes unit test failures.

Preferred way to run the tests
------------------------------

The preferred way to run the unit tests is using ``tox``.  See `the
unit testing section of the Testing wiki page`_ and Nova's HACKING.rst
for more information.  Following are some simple examples.

To run the Python 2.6 tests::

    tox -e py26

To run the style tests:

    tox -e pep8

You can request multiple tests, separated by commas::

    tox -e py27,pep8

Older way to run the tests
--------------------------

Using ``tox`` is preferred.  It is also possible to run the unit tests
using the ``run_tests.sh`` script found at the top level of the
project.  The remainder of this document is focused on
``run_tests.sh``.

Run the unit tests by doing::

    ./run_tests.sh

This script is a wrapper around the `testr`_ testrunner and the `flake8`_ checker.

.. _the unit testing section of the Testing wiki page: https://wiki.openstack.org/wiki/Testing#Unit_Tests
.. _testr: https://code.launchpad.net/testrepository
.. _flake8: https://github.com/bmcustodio/flake8

Flags
-----

The ``run_tests.sh`` script supports several flags. You can view a list of
flags by doing::

    run_tests.sh -h

This will show the following help information::

    Usage: ./run_tests.sh [OPTION]...
    Run Nova's test suite(s)

      -V, --virtual-env           Always use virtualenv.  Install automatically if not present
      -N, --no-virtual-env        Don't use virtualenv.  Run tests in local environment
      -s, --no-site-packages      Isolate the virtualenv from the global Python environment
      -f, --force                 Force a clean re-build of the virtual environment. Useful when dependencies have been added.
      -u, --update                Update the virtual environment with any newer package versions
      -p, --pep8                  Just run PEP8 and HACKING compliance check
      -P, --no-pep8               Don't run static code checks
      -c, --coverage              Generate coverage report
      -d, --debug                 Run tests with testtools instead of testr. This allows you to use the debugger.
      -h, --help                  Print this usage message
      --hide-elapsed              Don't print the elapsed time for each test along with slow test list
      --virtual-env-path <path>   Location of the virtualenv directory
                                   Default: $(pwd)
      --virtual-env-name <name>   Name of the virtualenv directory
                                   Default: .venv
      --tools-path <dir>          Location of the tools directory
                                   Default: $(pwd)

   Note: with no options specified, the script will try to run the tests in a virtual environment,
         If no virtualenv is found, the script will ask if you would like to create one.  If you
         prefer to run tests NOT in a virtual environment, simply pass the -N option.

Because ``run_tests.sh`` is a wrapper around testrepository, it also accepts the same
flags as testr. See the `testr user manual`_ for details about
these additional flags.

.. _testr user manual: https://testrepository.readthedocs.org/en/latest/MANUAL.html

Running a subset of tests
-------------------------

Instead of running all tests, you can specify an individual directory, file,
class, or method that contains test code.

To run the tests in the ``nova/tests/scheduler`` directory::

    ./run_tests.sh scheduler

To run the tests in the ``nova/tests/virt/libvirt/test_libvirt.py`` file::

    ./run_tests.sh test_libvirt

To run the tests in the ``CacheConcurrencyTestCase`` class in
``nova/tests/virt/libvirt/test_libvirt.py``::

    ./run_tests.sh test_libvirt.CacheConcurrencyTestCase

To run the `ValidateIntegerTestCase.test_invalid_inputs` test method in
``nova/tests/test_utils.py``::

    ./run_tests.sh test_utils.ValidateIntegerTestCase.test_invalid_inputs

Virtualenv
----------

By default, the tests use the Python packages installed inside a
virtualenv [#f2]_. (This is equivalent to using the ``-V, --virtualenv`` flag).
If the virtualenv does not exist, it will be created the first time the tests are run.

If you wish to recreate the virtualenv, call ``run_tests.sh`` with the flag::

    -f, --force

Recreating the virtualenv is useful if the package dependencies have changed
since the virtualenv was last created. If the ``requirements.txt`` or
``tools/install_venv.py`` files have changed, it's a good idea to recreate the
virtualenv.

By default, the unit tests will see both the packages in the virtualenv and
the packages that have been installed in the Python global environment. In
some cases, the packages in the Python global environment may cause a conflict
with the packages in the virtualenv. If this occurs, you can isolate the
virtualenv from the global environment by using the flag::

    -s, --no-site packages

If you do not wish to use a virtualenv at all, use the flag::

    -N, --no-virtual-env

Gotchas
-------

**Running Tests from Shared Folders**

If you are running the unit tests from a shared folder, you may see tests start
to fail or stop completely as a result of Python lockfile issues [#f4]_. You
can get around this by manually setting or updating the following line in
``nova/tests/conf_fixture.py``::

    FLAGS['lock_path'].SetDefault('/tmp')

Note that you may use any location (not just ``/tmp``!) as long as it is not
a shared folder.

.. rubric:: Footnotes

.. [#f1] See :doc:`jenkins`.

.. [#f2] See :doc:`development.environment` for more details about the use of
   virtualenv.

.. [#f3] There is an effort underway to use a fake DB implementation for the
   unit tests. See https://lists.launchpad.net/openstack/msg05604.html

.. [#f4] See Vish's comment in this bug report: https://bugs.launchpad.net/nova/+bug/882933
