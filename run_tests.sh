#!/bin/bash

set -eu

function usage {
  echo "Usage: $0 [OPTION]..."
  echo "Run Nova's test suite(s)"
  echo ""
  echo "  -V, --virtual-env           Always use virtualenv.  Install automatically if not present"
  echo "  -N, --no-virtual-env        Don't use virtualenv.  Run tests in local environment"
  echo "  -s, --no-site-packages      Isolate the virtualenv from the global Python environment"
  echo "  -f, --force                 Force a clean re-build of the virtual environment. Useful when dependencies have been added."
  echo "  -u, --update                Update the virtual environment with any newer package versions"
  echo "  -p, --pep8                  Just run PEP8 and HACKING compliance check"
  echo "  -8, --pep8-only-changed     Just run PEP8 and HACKING compliance check on files changed since HEAD~1"
  echo "  -P, --no-pep8               Don't run static code checks"
  echo "  -c, --coverage              Generate coverage report"
  echo "  -d, --debug                 Run tests with testtools instead of testr. This allows you to use the debugger."
  echo "  -h, --help                  Print this usage message"
  echo "  --hide-elapsed              Don't print the elapsed time for each test along with slow test list"
  echo "  --virtual-env-path <path>   Location of the virtualenv directory"
  echo "                               Default: \$(pwd)"
  echo "  --virtual-env-name <name>   Name of the virtualenv directory"
  echo "                               Default: .venv"
  echo "  --tools-path <dir>          Location of the tools directory"
  echo "                               Default: \$(pwd)"
  echo "  --concurrency <concurrency> How many processes to use when running the tests. A value of 0 autodetects concurrency from your CPU count"
  echo "                               Default: 0"
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
      -f|--force) force=1;;
      -u|--update) update=1;;
      -p|--pep8) just_pep8=1;;
      -8|--pep8-only-changed) just_pep8_changed=1;;
      -P|--no-pep8) no_pep8=1;;
      -c|--coverage) coverage=1;;
      -d|--debug) debug=1;;
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
      --concurrency)
        (( i++ ))
        concurrency=${!i}
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
just_pep8_changed=0
no_pep8=0
coverage=0
debug=0
update=0
concurrency=0

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

if [ $no_site_packages -eq 1 ]; then
  installvenvopts="--no-site-packages"
fi

function run_tests {
  # Cleanup *pyc
  ${wrapper} find . -type f -name "*.pyc" -delete

  if [ $debug -eq 1 ]; then
    if [ "$testropts" = "" ] && [ "$testrargs" = "" ]; then
      # Default to running all tests if specific test is not
      # provided.
      testrargs="discover ./nova/tests"
    fi
    ${wrapper} python -m testtools.run $testropts $testrargs

    # Short circuit because all of the testr and coverage stuff
    # below does not make sense when running testtools.run for
    # debugging purposes.
    return $?
  fi

  if [ $coverage -eq 1 ]; then
    TESTRTESTS="$TESTRTESTS --coverage"
  else
    TESTRTESTS="$TESTRTESTS"
  fi

  # Just run the test suites in current environment
  set +e
  testrargs=`echo "$testrargs" | sed -e's/^\s*\(.*\)\s*$/\1/'`
  TESTRTESTS="$TESTRTESTS --testr-args='--subunit --concurrency $concurrency $testropts $testrargs'"
  if [ setup.cfg -nt nova.egg-info/entry_points.txt ]
  then
    ${wrapper} python setup.py egg_info
  fi
  echo "Running \`${wrapper} $TESTRTESTS\`"
  if ${wrapper} which subunit-2to1 2>&1 > /dev/null
  then
    # subunit-2to1 is present, testr subunit stream should be in version 2
    # format. Convert to version one before colorizing.
    bash -c "${wrapper} $TESTRTESTS | ${wrapper} subunit-2to1 | ${wrapper} tools/colorizer.py"
  else
    bash -c "${wrapper} $TESTRTESTS | ${wrapper} tools/colorizer.py"
  fi
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

function warn_on_flake8_without_venv {
  if [ $never_venv -eq 1 ]; then
    echo "**WARNING**:"
    echo "Running flake8 without virtual env may miss OpenStack HACKING detection"
  fi
}

function run_pep8 {
  echo "Running flake8 ..."
  warn_on_flake8_without_venv
  bash -c "${wrapper} flake8"
}


TESTRTESTS="python setup.py testr"

if [ $never_venv -eq 0 ]
then
  # Remove the virtual environment if --force used
  if [ $force -eq 1 ]; then
    echo "Cleaning virtualenv..."
    rm -rf ${venv}
  fi
  if [ $update -eq 1 ]; then
      echo "Updating virtualenv..."
      python tools/install_venv.py $installvenvopts
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

if [ $just_pep8_changed -eq 1 ]; then
    # NOTE(gilliard) We want use flake8 to check the entirety of every file that has
    # a change in it. Unfortunately the --filenames argument to flake8 only accepts
    # file *names* and there are no files named (eg) "nova/compute/manager.py".  The
    # --diff argument behaves surprisingly as well, because although you feed it a
    # diff, it actually checks the file on disk anyway.
    files=$(git diff --name-only HEAD~1 | tr '\n' ' ')
    echo "Running flake8 on ${files}"
    warn_on_flake8_without_venv
    bash -c "diff -u --from-file /dev/null ${files} | ${wrapper} flake8 --diff"
    exit
fi

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
