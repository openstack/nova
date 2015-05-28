# Copyright (c) 2011 OpenStack Foundation
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

import operator

# 1. The following operations are supported:
#   =, s==, s!=, s>=, s>, s<=, s<, <in>, <all-in>, <or>, ==, !=, >=, <=
# 2. Note that <or> is handled in a different way below.
# 3. If the first word in the extra_specs is not one of the operators,
#   it is ignored.
op_methods = {'=': lambda x, y: float(x) >= float(y),
               '<in>': lambda x, y: y in x,
               '<all-in>': lambda x, y: all(val in x for val in y),
               '==': lambda x, y: float(x) == float(y),
               '!=': lambda x, y: float(x) != float(y),
               '>=': lambda x, y: float(x) >= float(y),
               '<=': lambda x, y: float(x) <= float(y),
               's==': operator.eq,
               's!=': operator.ne,
               's<': operator.lt,
               's<=': operator.le,
               's>': operator.gt,
               's>=': operator.ge}


def match(value, req):
    words = req.split()

    op = method = None
    if words:
        op = words.pop(0)
        method = op_methods.get(op)

    if op != '<or>' and not method:
        return value == req

    if value is None:
        return False

    if op == '<or>':  # Ex: <or> v1 <or> v2 <or> v3
        while True:
            if words.pop(0) == value:
                return True
            if not words:
                break
            words.pop(0)  # remove a keyword <or>
            if not words:
                break
        return False

    if words:
        if op == '<all-in>':  # requires a list not a string
            return method(value, words)
        return method(value, words[0])
    return False
