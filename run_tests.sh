#!/bin/bash

function usage {
  echo "Usage: $0 [OPTION]..."
  echo "Run Nova's test suite(s)"
  echo ""
  echo "  -V, --virtual-env        Always use virtualenv.  Install automatically if not present"
  echo "  -N, --no-virtual-env     Don't use virtualenv.  Run tests in local environment"
  echo "  -f, --force              Force a clean re-build of the virtual environment. Useful when dependencies have been added."
  echo "  -p, --pep8               Just run pep8"
  echo "  -h, --help               Print this usage message"
  echo ""
  echo "Note: with no options specified, the script will try to run the tests in a virtual environment,"
  echo "      If no virtualenv is found, the script will ask if you would like to create one.  If you "
  echo "      prefer to run tests NOT in a virtual environment, simply pass the -N option."
  exit
}

function process_option {
  case "$1" in
    -h|--help) usage;;
    -V|--virtual-env) let always_venv=1; let never_venv=0;;
    -N|--no-virtual-env) let always_venv=0; let never_venv=1;;
    -f|--force) let force=1;;
    -p|--pep8) let just_pep8=1;;
    *) noseargs="$noseargs $1"
  esac
}

venv=.nova-venv
with_venv=tools/with_venv.sh
always_venv=0
never_venv=0
force=0
noseargs=
wrapper=""
just_pep8=0

for arg in "$@"; do
  process_option $arg
done

function run_tests {
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

function run_pep8 {
  echo "Running pep8 ..."
  srcfiles=`find bin -type f ! -name "nova.conf*"`
  srcfiles+=" nova setup.py plugins/xenserver/xenapi/etc/xapi.d/plugins/glance"
  pep8 --repeat --show-pep8 --show-source --exclude=vcsversion.py ${srcfiles}
}

if [ $just_pep8 -eq 1 ]; then
    run_pep8
    exit
fi

NOSETESTS="python run_tests.py $noseargs"

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
      python tools/install_venv.py
      wrapper="${with_venv}"
    else
      echo -e "No virtual environment found...create one? (Y/n) \c"
      read use_ve
      if [ "x$use_ve" = "xY" -o "x$use_ve" = "x" -o "x$use_ve" = "xy" ]; then
        # Install the virtualenv and run the test suite in it
        python tools/install_venv.py
        wrapper=${with_venv}
      fi
    fi
  fi
fi

run_tests || exit

# Also run pep8 if no options were provided.
if [ -z "$noseargs" ]; then
  run_pep8
fi
