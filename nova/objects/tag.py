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

from nova import db
from nova import objects
from nova.objects import base
from nova.objects import fields


class Tag(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'resource_id': fields.StringField(),
        'tag': fields.StringField(),
        }

    @staticmethod
    def _from_db_object(context, tag, db_tag):
        for key in tag.fields:
            setattr(tag, key, db_tag[key])
        tag.obj_reset_changes()
        tag._context = context
        return tag

    @base.remotable
    def create(self, context):
        db_tag = db.instance_tag_add(context, self.resource_id, self.tag)
        self._from_db_object(context, self, db_tag)

    @base.remotable_classmethod
    def destroy(cls, context, resource_id, name):
        db.instance_tag_delete(context, resource_id, name)


class TagList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('Tag'),
        }
    child_versions = {
        '1.0': '1.0',
        }

    @base.remotable_classmethod
    def get_by_resource_id(cls, context, resource_id):
        db_tags = db.instance_tag_get_by_instance_uuid(context, resource_id)
        return base.obj_make_list(context, cls(), objects.Tag, db_tags)

    @base.remotable_classmethod
    def create(cls, context, resource_id, tags):
        db_tags = db.instance_tag_set(context, resource_id, tags)
        return base.obj_make_list(context, cls(), objects.Tag, db_tags)

    @base.remotable_classmethod
    def destroy(cls, context, resource_id):
        db.instance_tag_delete_all(context, resource_id)
