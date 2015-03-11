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


from oslo_db.sqlalchemy import models
from sqlalchemy import Column
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import schema
from sqlalchemy import String
from sqlalchemy import Text


class _NovaAPIBase(models.ModelBase, models.TimestampMixin):
    pass


API_BASE = declarative_base(cls=_NovaAPIBase)


class CellMapping(API_BASE):
    """Contains information on communicating with a cell"""
    __tablename__ = 'cell_mappings'
    __table_args__ = (Index('uuid_idx', 'uuid'),
                      schema.UniqueConstraint('uuid',
                          name='uniq_cell_mappings0uuid'))

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), nullable=False)
    name = Column(String(255))
    transport_url = Column(Text())
    database_connection = Column(Text())
