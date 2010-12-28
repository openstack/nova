#!/bin/bash

function usage {
  echo "Usage: $0 [OPTION]..."
  echo "Run Nova's test suite(s)"
  echo ""
  echo "  -V, --virtual-env        Always use virtualenv.  Install automatically if not present"
  echo "  -N, --no-virtual-env     Don't use virtualenv.  Run tests in local environment"
  echo "  -f, --force              Force a clean re-build of the virtual environment. Useful when dependencies have been added."
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
  esac
}

venv=.nova-venv
with_venv=tools/with_venv.sh
always_venv=0
never_venv=0
force=0


for arg in "$@"; do
  process_option $arg
done

if [ $never_venv -eq 1 ]; then
  # Just run the test suites in current environment
  rm -f nova.sqlite
  python run_tests.py $@ 2> run_tests.err.log
  exit
fi

# Remove the virtual environment if --force used
if [ $force -eq 1 ]; then
  echo "Cleaning virtualenv..."
  rm -rf ${venv}
fi

if [ -e ${venv} ]; then
  ${with_venv} rm -f nova.sqlite
  ${with_venv} python run_tests.py $@ 2> run_tests.err.log
else  
  if [ $always_venv -eq 1 ]; then
    # Automatically install the virtualenv
    python tools/install_venv.py
  else
    echo -e "No virtual environment found...create one? (Y/n) \c"
    read use_ve
    if [ "x$use_ve" = "xY" -o "x$use_ve" = "x" -o "x$use_ve" = "xy" ]; then
      # Install the virtualenv and run the test suite in it
      python tools/install_venv.py
    else
      rm -f nova.sqlite
      #nosetests -v
      python run_tests.py 2> run_tests.err.log
      exit
    fi
  fi
  ${with_venv} rm -f nova.sqlite
  ${with_venv} python run_tests.py $@ 2> run_tests.err.log
fi
