#!/bin/bash

set -eu

function usage {
  echo "Usage: $0 [OPTION]..."
  echo "Run Nova's test suite(s)"
  echo ""
  echo "  -V, --virtual-env        Always use virtualenv.  Install automatically if not present"
  echo "  -N, --no-virtual-env     Don't use virtualenv.  Run tests in local environment"
  echo "  -s, --no-site-packages   Isolate the virtualenv from the global Python environment"
  echo "  -r, --recreate-db        Recreate the test database (deprecated, as this is now the default)."
  echo "  -n, --no-recreate-db     Don't recreate the test database."
  echo "  -f, --force              Force a clean re-build of the virtual environment. Useful when dependencies have been added."
  echo "  -p, --pep8               Just run PEP8 and HACKING compliance check"
  echo "  -P, --no-pep8            Don't run static code checks"
  echo "  -c, --coverage           Generate coverage report"
  echo "  -h, --help               Print this usage message"
  echo "  --hide-elapsed           Don't print the elapsed time for each test along with slow test list"
  echo ""
  echo "Note: with no options specified, the script will try to run the tests in a virtual environment,"
  echo "      If no virtualenv is found, the script will ask if you would like to create one.  If you "
  echo "      prefer to run tests NOT in a virtual environment, simply pass the -N option."
  exit
}

function process_option {
  case "$1" in
    -h|--help) usage;;
    -V|--virtual-env) always_venv=1; never_venv=0;;
    -N|--no-virtual-env) always_venv=0; never_venv=1;;
    -s|--no-site-packages) no_site_packages=1;;
    -r|--recreate-db) recreate_db=1;;
    -n|--no-recreate-db) recreate_db=0;;
    -f|--force) force=1;;
    -p|--pep8) just_pep8=1;;
    -P|--no-pep8) no_pep8=1;;
    -c|--coverage) coverage=1;;
    -*) testropts="$testropts $1";;
    *) testrargs="$testrargs $1"
  esac
}

venv=.venv
with_venv=tools/with_venv.sh
always_venv=0
never_venv=0
force=0
no_site_packages=0
installvenvopts=
testrargs=
testropts=
wrapper=""
just_pep8=0
no_pep8=0
coverage=0
recreate_db=1

LANG=en_US.UTF-8
LANGUAGE=en_US:en
LC_ALL=C
OS_STDOUT_NOCAPTURE=False
OS_STDERR_NOCAPTURE=False

for arg in "$@"; do
  process_option $arg
done

if [ $no_site_packages -eq 1 ]; then
  installvenvopts="--no-site-packages"
fi

function init_testr {
  if [ ! -d .testrepository ]; then
    ${wrapper} testr init
  fi
}

function run_tests {
  # Cleanup *pyc
  ${wrapper} find . -type f -name "*.pyc" -delete

  if [ $coverage -eq 1 ]; then
    # Do not test test_coverage_ext when gathering coverage.
    if [ "x$testrargs" = "x" ]; then
      testrargs = "^(?!.*test_coverage_ext).*$"
    fi
    export PYTHON="${wrapper} coverage run --source nova --parallel-mode"
  fi
  # Just run the test suites in current environment
  set +e
  TESTRTESTS="$TESTRTESTS $testrargs"
  echo "Running \`${wrapper} $TESTRTESTS\`"
  ${wrapper} $TESTRTESTS
  RESULT=$?
  set -e

  copy_subunit_log

  return $RESULT
}

function copy_subunit_log {
  LOGNAME=`cat .testrepository/next-stream`
  LOGNAME=$(($LOGNAME - 1))
  LOGNAME=".testrepository/${LOGNAME}"
  cp $LOGNAME subunit.log
}

function run_pep8 {
  echo "Running PEP8 and HACKING compliance check..."

  # Files of interest
  # NOTE(lzyeval): Avoid selecting nova-api-paste.ini and nova.conf in nova/bin
  #                when running on devstack.
  # NOTE(lzyeval): Avoid selecting *.pyc files to reduce pep8 check-up time
  #                when running on devstack.
  srcfiles=`find nova -type f -name "*.py" ! -wholename "nova\/openstack*"`
  srcfiles+=" `find bin -type f ! -name "nova.conf*" ! -name "*api-paste.ini*"`"
  srcfiles+=" `find tools -type f -name "*.py"`"
  srcfiles+=" setup.py"

  # Until all these issues get fixed, ignore.
  ignore='--ignore=N4,E12,E711,E721,E712'

  ${wrapper} python tools/hacking.py ${ignore} ${srcfiles}

  # NOTE(sirp): Dom0 plugins are written for Python 2.4, meaning some HACKING
  #             checks are too strict.
  pep8onlyfiles=`find plugins -type f -name "*.py"`
  pep8onlyfiles+=" `find plugins/xenserver/xenapi/etc/xapi.d/plugins/ -type f -perm +111`"
  ${wrapper} pep8 ${ignore} ${pep8onlyfiles}
}


TESTRTESTS="testr run --parallel $testropts"

if [ $never_venv -eq 0 ]
then
  # Remove the virtual environment if --force used
  if [ $force -eq 1 ]; then
    echo "Cleaning virtualenv..."
    rm -rf ${venv}
  fi
  if [ -e ${venv} ]; then
    wrapper="${with_venv}"
  else
    if [ $always_venv -eq 1 ]; then
      # Automatically install the virtualenv
      python tools/install_venv.py $installvenvopts
      wrapper="${with_venv}"
    else
      echo -e "No virtual environment found...create one? (Y/n) \c"
      read use_ve
      if [ "x$use_ve" = "xY" -o "x$use_ve" = "x" -o "x$use_ve" = "xy" ]; then
        # Install the virtualenv and run the test suite in it
        python tools/install_venv.py $installvenvopts
        wrapper=${with_venv}
      fi
    fi
  fi
fi

# Delete old coverage data from previous runs
if [ $coverage -eq 1 ]; then
    ${wrapper} coverage erase
fi

if [ $just_pep8 -eq 1 ]; then
    run_pep8
    exit
fi

if [ $recreate_db -eq 1 ]; then
    rm -f tests.sqlite
fi

init_testr
run_tests

# NOTE(sirp): we only want to run pep8 when we're running the full-test suite,
# not when we're running tests individually. To handle this, we need to
# distinguish between options (testropts), which begin with a '-', and
# arguments (testrargs).
if [ -z "$testrargs" ]; then
  if [ $no_pep8 -eq 0 ]; then
    run_pep8
  fi
fi

if [ $coverage -eq 1 ]; then
    echo "Generating coverage report in covhtml/"
    # Don't compute coverage for common code, which is tested elsewhere
    ${wrapper} coverage combine
    ${wrapper} coverage html --include='nova/*' --omit='nova/openstack/common/*' -d covhtml -i
fi
