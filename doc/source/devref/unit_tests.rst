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

.. _the unit testing section of the Testing wiki page: https://wiki.openstack.org/wiki/Testing#Unit_Tests

Running a subset of tests
-------------------------

Instead of running all tests, you can specify an individual directory, file,
class, or method that contains test code.

To run the tests in the ``nova/tests/scheduler`` directory::

    tox -e py27 nova.tests.scheduler

To run the tests in the ``nova/tests/virt/libvirt/test_libvirt.py`` file::

    tox -e py27 test_libvirt

To run the tests in the ``CacheConcurrencyTestCase`` class in
``nova/tests/virt/libvirt/test_libvirt.py``::

    tox -e py27  test_libvirt.CacheConcurrencyTestCase

To run the `ValidateIntegerTestCase.test_invalid_inputs` test method in
``nova/tests/test_utils.py``::

    tox -epy27 test_utils.ValidateIntegerTestCase.test_invalid_inputs

.. rubric:: Footnotes

.. [#f1] See :doc:`jenkins`.
