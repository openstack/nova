#!/bin/bash

set -eu

function usage {
  echo "Usage: $0 [OPTION]..."
  echo "Run Nova's test suite(s)"
  echo ""
  echo "  -V, --virtual-env           Always use virtualenv.  Install automatically if not present"
  echo "  -N, --no-virtual-env        Don't use virtualenv.  Run tests in local environment"
  echo "  -s, --no-site-packages      Isolate the virtualenv from the global Python environment"
  echo "  -r, --recreate-db           Recreate the test database (deprecated, as this is now the default)."
  echo "  -n, --no-recreate-db        Don't recreate the test database."
  echo "  -f, --force                 Force a clean re-build of the virtual environment. Useful when dependencies have been added."
  echo "  -p, --pep8                  Just run PEP8 and HACKING compliance check"
  echo "  -P, --no-pep8               Don't run static code checks"
  echo "  -c, --coverage              Generate coverage report"
  echo "  -h, --help                  Print this usage message"
  echo "  --hide-elapsed              Don't print the elapsed time for each test along with slow test list"
  echo "  --virtual-env-path <path>   Location of the virtualenv directory"
  echo "                               Default: \$(pwd)"
  echo "  --virtual-env-name <name>   Name of the virtualenv directory"
  echo "                               Default: .venv"
  echo "  --tools-path <dir>          Location of the tools directory"
  echo "                               Default: \$(pwd)"
  echo ""
  echo "Note: with no options specified, the script will try to run the tests in a virtual environment,"
  echo "      If no virtualenv is found, the script will ask if you would like to create one.  If you "
  echo "      prefer to run tests NOT in a virtual environment, simply pass the -N option."
  exit
}

function process_options {
  i=1
  while [ $i -le $# ]; do
    case "${!i}" in
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
      --virtual-env-path)
        (( i++ ))
        venv_path=${!i}
        ;;
      --virtual-env-name)
        (( i++ ))
        venv_dir=${!i}
        ;;
      --tools-path)
        (( i++ ))
        tools_path=${!i}
        ;;
      -*) testropts="$testropts ${!i}";;
      *) testrargs="$testrargs ${!i}"
    esac
    (( i++ ))
  done
}

tool_path=${tools_path:-$(pwd)}
venv_path=${venv_path:-$(pwd)}
venv_dir=${venv_name:-.venv}
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

process_options $@
# Make our paths available to other scripts we call
export venv_path
export venv_dir
export venv_name
export tools_dir
export venv=${venv_path}/${venv_dir}

SCRIPT_ROOT=$(dirname $(readlink -f "$0"))

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
      testrargs="^(?!.*test.*coverage).*$"
    fi
    TESTRTESTS="$TESTRTESTS --coverage"
  else
    TESTRTESTS="$TESTRTESTS --slowest"
  fi

  # Just run the test suites in current environment
  set +e
  testrargs=`echo "$testrargs" | sed -e's/^\s*\(.*\)\s*$/\1/'`
  TESTRTESTS="$TESTRTESTS --testr-args='--subunit $testropts $testrargs'"
  echo "Running \`${wrapper} $TESTRTESTS\`"
  bash -c "${wrapper} $TESTRTESTS | ${wrapper} subunit2pyunit"
  RESULT=$?
  set -e

  copy_subunit_log

  if [ $coverage -eq 1 ]; then
    echo "Generating coverage report in covhtml/"
    # Don't compute coverage for common code, which is tested elsewhere
    ${wrapper} coverage combine
    ${wrapper} coverage html --include='nova/*' --omit='nova/openstack/common/*' -d covhtml -i
  fi

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
  srcfiles+=" `find bin -type f ! -name "nova.conf*" ! -name "*api-paste.ini*" ! -name "*~"`"
  srcfiles+=" `find tools -type f -name "*.py"`"
  srcfiles+=" `find smoketests -type f -name "*.py"`"
  srcfiles+=" setup.py"

  # Until all these issues get fixed, ignore.
  ignore='--ignore=E12,E711,E721,E712,N403,N404,N303'

  # First run the hacking selftest, to make sure it's right
  echo "Running hacking.py self test"
  ${wrapper} python tools/hacking.py --doctest

  # Then actually run it
  echo "Running pep8"
  ${wrapper} python tools/hacking.py ${ignore} ${srcfiles}

  PYTHONPATH=$SCRIPT_ROOT/plugins/xenserver/networking/etc/xensource/scripts ${wrapper} python tools/hacking.py ${ignore} ./plugins/xenserver/networking

  PYTHONPATH=$SCRIPT_ROOT/plugins/xenserver/xenapi/etc/xapi.d/plugins ${wrapper} python tools/hacking.py ${ignore} ./plugins/xenserver/xenapi

  ${wrapper} bash tools/unused_imports.sh
  # NOTE(sdague): as of grizzly-2 these are passing however leaving the comment
  # in here in case we need to break it out when we get more of our hacking working
  # again.
  #
  # NOTE(sirp): Dom0 plugins are written for Python 2.4, meaning some HACKING
  #             checks are too strict.
  # pep8onlyfiles=`find plugins -type f -name "*.py"`
  # pep8onlyfiles+=" `find plugins/xenserver/xenapi/etc/xapi.d/plugins/ -type f -perm +111`"
  # ${wrapper} pep8 ${ignore} ${pep8onlyfiles}
}


TESTRTESTS="python setup.py testr"

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
