# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Rackspace Hosting
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

"""
MySQLdb sql operators, etc.
"""

class Literal(object):
    def __init__(self, value):
        self.value = value


class Operator(object):
    op = None

    def __init__(self, *values):
        self.values = []
        for val in values:
            try:
                for k, v in val.iteritems():
                    self.values.append(EQ(k, v))
            except AttributeError:
                self.values.append(val)

    def to_mysql(self):
        str_ = ''
        args = []

        def _value(value):
            if isinstance(value, Literal):
                return value.value
            args.append(value)
            return '%s'

        for value in self.values:
            if str_:
                str_ += ' %s ' % self.op
            try:
                op_str, op_args = value.to_mysql()
                str_ += '(' + op_str  + ')'
                args.extend(op_args)
                continue
            except AttributeError:
                pass
            if isinstance(value, (list, tuple)):
                str_ += '(' + ','.join([_value(v) for v in value]) + ')'
            else:
                str_ += _value(value)
        return str_, args


class OR(Operator):
    op = 'OR'


class AND(Operator):
    op = 'AND'


class IS(Operator):
    op = 'IS'


class EQ(Operator):
    op = '='


class NE(Operator):
    op = '!='


class IN(Operator):
    op = 'IN'


class NOTIN(Operator):
    op = 'NOT IN'


class _BaseWhereOrOn(object):
    def __init__(self, clause):
        if isinstance(clause, (list, tuple)):
            clause = AND(*clause)
        self.clause = clause

    def to_mysql(self):
        clause_str, clause_args = self.clause.to_mysql()
        return self.kw + ' ' + clause_str, clause_args


class Where(_BaseWhereOrOn):
    kw = 'WHERE'


class On(_BaseWhereOrOn):
    kw = 'ON'


class Join(object):
    def __init__(self, table, clause, jointype=None, use_list=True,
                 target=None):
        self.table = table
        self.use_list = use_list
        self.on = On(clause)
        self.target = target and target or table
        if jointype is None:
            jointype = 'LEFT OUTER JOIN'
        self.jointype = jointype

    def to_mysql(self):
        on_str, on_args = self.on.to_mysql()
        join_str = '%s %s as %s' % (self.jointype, self.table,
                                    self.target) + '\n  ' + on_str
        return join_str, on_args
