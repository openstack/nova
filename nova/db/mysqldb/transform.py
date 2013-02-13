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
Translate SQL result rows into dictionaries that Nova code is used to working
with.
"""
from nova.db.mysqldb import models


def to_objects(rows, table, joins):
    """Return a list of dictionaries representing the objects returned."""
    tables = models.get_schema()['tables']
    result_dict = {}

    for row in rows:
        _xform_row(result_dict, table, row, joins, tables)

    return _to_list(result_dict, joins)


def _xform_row(result_dict, table, row, joins, tables):
    col_iter = iter(row)

    # All of the columns for our table come first.
    this_obj = {}
    for column in tables[table]:
        this_obj[column] = col_iter.next()

    main_obj = result_dict.setdefault(this_obj['id'], this_obj)

    # Now the joined tables in order.  We'll create dictionaries
    # within the main object for these.. with the key being 'id'.
    # This resolves duplicates.  We'll turn them back into lists
    # or single objects below
    for join in joins:
        join_obj = {}
        for column in tables[join.table]:
            join_obj[column] = col_iter.next()
        j2 = main_obj.setdefault(join.target, {})

        # skip empty joins
        if join_obj['id'] is not None:
            j2[join_obj['id']] = join_obj

    try:
        col_iter.next()
        # FIX ME -- This means the DB has changed.  We'll want
        # to raise something here and catch and re-try
        raise SystemError
    except StopIteration:
        pass


def _to_list(result_dict, joins):

    results = []
    # Turn the joins from dictionaries into lists or single objects
    # depending on what is desired.
    for obj in result_dict.itervalues():
        for join in joins:
            target = join.target
            values = obj[target].values()
            if join.use_list:
                obj[target] = values
            else:
                if len(values):
                    obj[target] = values[0]
                else:
                    obj[target] = None
        results.append(obj)
    return results


