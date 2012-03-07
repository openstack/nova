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
  echo "  -x, --stop               Stop running tests after the first error or failure."
  echo "  -f, --force              Force a clean re-build of the virtual environment. Useful when dependencies have been added."
  echo "  -p, --pep8               Just run pep8"
  echo "  -P, --no-pep8            Don't run pep8"
  echo "  -H, --hacking            Just run HACKING compliance testing"
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
    -m|--patch-migrate) patch_migrate=1;;
    -w|--no-patch-migrate) patch_migrate=0;;
    -f|--force) force=1;;
    -p|--pep8) just_pep8=1;;
    -P|--no-pep8) no_pep8=1;;
    -H|--hacking) just_hacking=1;;
    -c|--coverage) coverage=1;;
    -*) noseopts="$noseopts $1";;
    *) noseargs="$noseargs $1"
  esac
}

venv=.venv
with_venv=tools/with_venv.sh
always_venv=0
never_venv=0
force=0
no_site_packages=0
installvenvopts=
noseargs=
noseopts=
wrapper=""
just_pep8=0
no_pep8=0
just_hacking=0
coverage=0
recreate_db=1
patch_migrate=1

for arg in "$@"; do
  process_option $arg
done

# If enabled, tell nose to collect coverage data
if [ $coverage -eq 1 ]; then
    noseopts="$noseopts --with-coverage --cover-package=nova"
fi

if [ $no_site_packages -eq 1 ]; then
  installvenvopts="--no-site-packages"
fi

function run_tests {
  # Cleanup *pyc
  echo "cleaning *.pyc files"
  ${wrapper} find . -type f -name "*.pyc" -delete
  # Just run the test suites in current environment
  ${wrapper} $NOSETESTS 2> run_tests.log
  # If we get some short import error right away, print the error log directly
  RESULT=$?
  if [ "$RESULT" -ne "0" ];
  then
    ERRSIZE=`wc -l run_tests.log | awk '{print \$1}'`
    if [ "$ERRSIZE" -lt "40" ];
    then
        cat run_tests.log
    fi
  fi
  return $RESULT
}

# Files of interest
# NOTE(lzyeval): Avoid selecting nova-api-paste.ini and nova.conf in nova/bin
#                when running on devstack.
# NOTE(lzyeval): Avoid selecting *.pyc files to reduce pep8 check-up time
#                when running on devstack.
xen_api_path="plugins/xenserver/xenapi/etc/xapi.d/plugins"
xen_net_path="plugins/xenserver/networking/etc/xensource/scripts"
srcfiles=`find nova -type f -name "*.py"`
srcfiles+=" `find bin -type f ! -name "nova.conf*" ! -name "*api-paste.ini*"`"
srcfiles+=" `find tools -type f -name "*.py"`"
srcfiles+=" `find ${xen_api_path} ${xen_net_path} -type f ! -name "*.patch" ! -name "*.pyc"`"
srcfiles+=" setup.py"

function run_pep8 {
  echo "Running pep8 ..."
  # Just run PEP8 in current environment
  #
  # NOTE(sirp): W602 (deprecated 3-arg raise) is being ignored for the
  # following reasons:
  #
  #  1. It's needed to preserve traceback information when re-raising
  #     exceptions; this is needed b/c Eventlet will clear exceptions when
  #     switching contexts.
  #
  #  2. There doesn't appear to be an alternative, "pep8-tool" compatible way of doing this
  #     in Python 2 (in Python 3 `with_traceback` could be used).
  #
  #  3. Can find no corroborating evidence that this is deprecated in Python 2
  #     other than what the PEP8 tool claims. It is deprecated in Python 3, so,
  #     perhaps the mistake was thinking that the deprecation applied to Python 2
  #     as well.
  pep8_opts="--ignore=W602 --repeat"
  ${wrapper} pep8 ${pep8_opts} ${srcfiles}
}

function run_hacking {
  echo "Running hacking compliance testing..."
  hacking_opts="--ignore=E202,W602 --repeat"
  ${wrapper} python tools/hacking.py ${hacking_opts} ${srcfiles}
}


NOSETESTS="python nova/testing/runner.py $noseopts $noseargs"

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

if [ $just_hacking -eq 1 ]; then
    run_hacking
    exit
fi


if [ $recreate_db -eq 1 ]; then
    rm -f tests.sqlite
fi

run_tests

# NOTE(sirp): we only want to run pep8 when we're running the full-test suite,
# not when we're running tests individually. To handle this, we need to
# distinguish between options (noseopts), which begin with a '-', and
# arguments (noseargs).
if [ -z "$noseargs" ]; then
  if [ $no_pep8 -eq 0 ]; then
    run_pep8
  fi
fi

if [ $coverage -eq 1 ]; then
    echo "Generating coverage report in covhtml/"
    ${wrapper} coverage html -d covhtml -i
fi
