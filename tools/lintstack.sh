#!/usr/bin/env bash

# Copyright (c) 2012, AT&T Labs, Yun Mao <yunmao@gmail.com>
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

# Use lintstack.py to compare pylint errors between HEAD and HEAD~1

set -e
TOOLS_DIR=$(cd $(dirname "$0") && pwd)
GITHEAD=`git rev-parse HEAD`
cp -f $TOOLS_DIR/lintstack.py $TOOLS_DIR/lintstack.head.py
git checkout HEAD~1
# First generate tools/pylint_exceptions from HEAD~1
$TOOLS_DIR/lintstack.head.py generate
# Then use that as a reference to compare against HEAD
git checkout $GITHEAD
$TOOLS_DIR/lintstack.head.py
echo "Check passed. FYI: the pylint exceptions are:"
cat $TOOLS_DIR/pylint_exceptions
echo
echo "You are in detached HEAD mode. If you are a developer"
echo "and not very familiar with git, you might want to do"
echo "'git checkout branch-name' to go back to your branch."

