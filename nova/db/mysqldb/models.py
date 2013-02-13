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
MySQLdb models
"""
from nova.db.mysqldb import sql


class _BaseModel(object):
    @classmethod
    def _format(cls, tables, rows, joins):
        """Return a list of dictionaries representing the objects returned."""
        result_dict = {}

        for row in rows:
            col_iter = iter(row)

            # All of the columns for our table come first.
            this_obj = {}
            for column in tables[cls.__table__]:
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
                j2[join_obj['id']] = join_obj

            try:
                col_iter.next()
                # FIX ME -- This means the DB has changed.  We'll want
                # to raise something here and catch and re-try
                raise SystemError
            except StopIteration:
                pass

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

    @classmethod
    def select(cls, conn, names_to_join=None, clauses=None):
        if names_to_join is None:
            names_to_join = cls._default_joins
        if clauses:
            where = sql.Where(clauses)
        else:
            where = None
        joins = [getattr(cls, join_name) for join_name in names_to_join]
        results = conn.select(cls.__table__, joins=joins, where=where)
        return cls._format(conn.tables, results, joins)


class Instance(_BaseModel):
    __table__ = 'instances'

    info_cache = sql.Join('instance_info_caches',
        sql.EQ(sql.Literal('info_cache.instance_uuid'),
               sql.Literal('self.uuid')),
        use_list=False,
        target='info_cache')

    metadata = sql.Join('instance_metadata',
        sql.AND(sql.EQ(sql.Literal('metadata.instance_uuid'),
                       sql.Literal('self.uuid')),
                sql.EQ(sql.Literal('metadata.deleted'), 0)),
        target='metadata')

    system_metadata = sql.Join('instance_system_metadata',
        sql.AND(sql.EQ(sql.Literal('system_metadata.instance_uuid'),
                       sql.Literal('self.uuid')),
                sql.EQ(sql.Literal('system_metadata.deleted'), 0)),
        target='system_metadata')

    instance_type = sql.Join('instance_types',
        sql.EQ(sql.Literal('instance_type.id'),
               sql.Literal('self.instance_type_id')),
        use_list=False,
        target='instance_type')

    _possible_joins = ['info_cache', 'metadata', 'system_metadata',
                       'instance_type']
    _default_joins = _possible_joins
