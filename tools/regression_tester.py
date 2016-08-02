#!/usr/bin/env python
# Copyright (c) 2013 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


"""Tool for checking if patch contains a regression test.

By default runs against current patch but can be set to use any gerrit review
as specified by change number (uses 'git review -d').

Idea: take tests from patch to check, and run against code from previous patch.
If new tests pass, then no regression test, if new tests fails against old code
then either
* new tests depend on new code and cannot confirm regression test is valid
  (false positive)
* new tests detects the bug being fixed (detect valid regression test)
Due to the risk of false positives, the results from this need some human
interpretation.
"""

from __future__ import print_function

import optparse
import string
import subprocess
import sys


def run(cmd, fail_ok=False):
    print("running: %s" % cmd)
    obj = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           shell=True)
    obj.wait()
    if obj.returncode != 0 and not fail_ok:
        print("The above command terminated with an error.")
        sys.exit(obj.returncode)
    return obj.stdout.read()


def main():
    usage = """
    Tool for checking if a patch includes a regression test.

    Usage: %prog [options]"""
    parser = optparse.OptionParser(usage)
    parser.add_option("-r", "--review", dest="review",
                      help="gerrit review number to test")
    (options, args) = parser.parse_args()
    if options.review:
        original_branch = run("git rev-parse --abbrev-ref HEAD")
        run("git review -d %s" % options.review)
    else:
        print("no gerrit review number specified, running on latest commit"
              "on current branch.")

    test_works = False

    # run new tests with old code
    run("git checkout HEAD^ nova")
    run("git checkout HEAD nova/tests")

    # identify which tests have changed
    tests = run("git whatchanged --format=oneline -1 | grep \"nova/tests\" "
                "| cut -f2").split()
    test_list = []
    for test in tests:
        test_list.append(string.replace(test[0:-3], '/', '.'))

    if not test_list:
        test_works = False
        expect_failure = ""
    else:
        # run new tests, expect them to fail
        expect_failure = run(("tox -epy27 %s 2>&1" % string.join(test_list)),
                             fail_ok=True)
        if "FAILED (id=" in expect_failure:
            test_works = True

    # cleanup
    run("git checkout HEAD nova")
    if options.review:
        new_branch = run("git status | head -1 | cut -d ' ' -f 4")
        run("git checkout %s" % original_branch)
        run("git branch -D %s" % new_branch)

    print(expect_failure)
    print("")
    print("*******************************")
    if test_works:
        print("FOUND a regression test")
    else:
        print("NO regression test")
        sys.exit(1)


if __name__ == "__main__":
    main()
