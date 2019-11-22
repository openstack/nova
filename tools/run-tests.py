#!/usr/bin/env python
#
# Copyright (c) 2019 SUSE
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.  See the License for the specific language governing
# permissions and limitations under the License.


# Filters list of files on STDIN for test files (can be more than one
# per line), and runs any which can be run in the current tox
# virtualenv.  Automatically detects which stestr options to use,
# e.g. --test-path=./nova/tests/functional if we're in a virtualenv
# for functional tests.

import os
import re
import subprocess
import sys


def get_tox_env():
    if os.getenv('VIRTUAL_ENV', '').find('/.tox/') == -1:
        sys.stderr.write(
            """%s should be run within a tox virtualenv.
Please first activate the tox virtualenv you want to use, e.g.

    source .tox/py36/bin/activate
""" %
            os.path.realpath(__file__))
        sys.exit(1)

    return os.getenv('VIRTUAL_ENV')


def tox_env_is_functional():
    return get_tox_env().find('.tox/functional') != -1


def get_stestr_opts():
    opts = sys.argv[1:]

    if tox_env_is_functional():
        opts = ['--test-path=./nova/tests/functional'] + opts

    return opts


def get_test_files():
    test_files = []
    functional = tox_env_is_functional()

    for line in sys.stdin:
        files = line.strip().split()
        for f in files:
            if not re.match(r'^nova/tests/.*\.py$', f):
                # In the future we could get really clever and
                # map source files to their corresponding tests,
                # as is typically done by Guardfile in projects
                # which use Guard: https://guardgem.org
                continue

            functional_re = r'^nova/tests/functional/'
            if functional:
                if not re.match(functional_re, f):
                    continue
            else:
                if re.match(functional_re, f):
                    continue

            test_files.append(f[:-3].replace('/', '.'))

    return test_files


def main():
    stestr_opts = get_stestr_opts()
    test_files = get_test_files()

    if not test_files:
        print("No test files found to run")
        sys.exit(0)

    if len(test_files) == 1:
        # If there's only one module to run (or test therein), we can
        # skip discovery which will chop quite a few seconds off the
        # runtime.
        stestr_opts = ['-n'] + stestr_opts

    cmd = ['stestr', 'run', *stestr_opts] + test_files
    print(' '.join(cmd))
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print("\nstestr returned non-zero exit code %d\n" % e.returncode)


if __name__ == '__main__':
    main()
