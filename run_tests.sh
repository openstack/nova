#!/bin/bash

set -eu

cat <<EOF
run_tests.sh is deprecated and this script will be removed
before the Mitaka release. All tests should be run through
tox.

To run style checks:

 tox -e pep8

To run python 2.7 unit tests

 tox -e py27

To run functional tests

 tox -e functional

To run a subset of any of these tests:

 tox -e py27 someregex

 i.e.: tox -e py27 test_servers

Use following to replace './run_test.sh -8' to do pep8 check with changed files

 tox -e pep8 -- -HEAD

Additional tox targets are available in tox.ini. For more information
see:
http://docs.openstack.org/project-team-guide/project-setup/python.html

NOTE: if you really really don't want to use tox to run tests, you
can instead use:

 testr run

Documentation on using testr directly can be found at
http://testrepository.readthedocs.org/en/latest/MANUAL.html

EOF

exit 1
