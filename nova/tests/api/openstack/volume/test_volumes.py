# Copyright 2013 Josh Durgin
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

import datetime

from lxml import etree

from nova.api.openstack.volume import volumes
from nova import flags
from nova import test


FLAGS = flags.FLAGS


class VolumeSerializerTest(test.TestCase):
    def _verify_volume_attachment(self, attach, tree):
        for attr in ('id', 'volumeId', 'serverId', 'device'):
            self.assertEqual(str(attach[attr]), tree.get(attr))

    def _verify_volume(self, vol, tree):
        self.assertEqual(tree.tag, 'volume')

        for attr in ('id', 'status', 'size', 'availabilityZone', 'createdAt',
                     'displayName', 'displayDescription', 'volumeType',
                     'snapshotId'):
            self.assertEqual(str(vol[attr]), tree.get(attr))

        for child in tree:
            self.assertTrue(child.tag in ('attachments', 'metadata'))
            if child.tag == 'attachments':
                self.assertEqual(1, len(child))
                self.assertEqual('attachment', child[0].tag)
                self._verify_volume_attachment(vol['attachments'][0], child[0])
            elif child.tag == 'metadata':
                not_seen = set(vol['metadata'].keys())
                for gr_child in child:
                    self.assertTrue(gr_child.tag in not_seen)
                    self.assertEqual(str(vol['metadata'][gr_child.tag]),
                                     gr_child.text)
                    not_seen.remove(gr_child.tag)
                self.assertEqual(0, len(not_seen))

    def test_attach_show_create_serializer(self):
        serializer = volumes.VolumeAttachmentSerializer()
        raw_attach = dict(
            id='vol_id',
            volumeId='vol_id',
            serverId='instance_uuid',
            device='/foo')
        text = serializer.serialize(dict(volumeAttachment=raw_attach), 'show')

        print text
        tree = etree.fromstring(text)

        self.assertEqual('volumeAttachment', tree.tag)
        self._verify_volume_attachment(raw_attach, tree)

    def test_attach_index_serializer(self):
        serializer = volumes.VolumeAttachmentSerializer()
        raw_attaches = [dict(
                id='vol_id1',
                volumeId='vol_id1',
                serverId='instance1_uuid',
                device='/foo1'),
                        dict(
                id='vol_id2',
                volumeId='vol_id2',
                serverId='instance2_uuid',
                device='/foo2')]
        text = serializer.serialize(dict(volumeAttachments=raw_attaches),
                                    'index')

        print text
        tree = etree.fromstring(text)

        self.assertEqual('volumeAttachments', tree.tag)
        self.assertEqual(len(raw_attaches), len(tree))
        for idx, child in enumerate(tree):
            self.assertEqual('volumeAttachment', child.tag)
            self._verify_volume_attachment(raw_attaches[idx], child)

    def test_volume_show_create_serializer(self):
        serializer = volumes.VolumeSerializer()
        raw_volume = dict(
            id='vol_id',
            status='vol_status',
            size=1024,
            availabilityZone='vol_availability',
            createdAt=datetime.datetime.now(),
            attachments=[dict(
                    id='vol_id',
                    volumeId='vol_id',
                    serverId='instance_uuid',
                    device='/foo')],
            displayName='vol_name',
            displayDescription='vol_desc',
            volumeType='vol_type',
            snapshotId='snap_id',
            metadata=dict(
                foo='bar',
                baz='quux',
                ),
            )
        text = serializer.serialize(dict(volume=raw_volume), 'show')

        print text
        tree = etree.fromstring(text)

        self._verify_volume(raw_volume, tree)

    def test_volume_index_detail_serializer(self):
        serializer = volumes.VolumeSerializer()
        raw_volumes = [dict(
                id='vol1_id',
                status='vol1_status',
                size=1024,
                availabilityZone='vol1_availability',
                createdAt=datetime.datetime.now(),
                attachments=[dict(
                        id='vol1_id',
                        volumeId='vol1_id',
                        serverId='instance_uuid',
                        device='/foo1')],
                displayName='vol1_name',
                displayDescription='vol1_desc',
                volumeType='vol1_type',
                snapshotId='snap1_id',
                metadata=dict(
                    foo='vol1_foo',
                    bar='vol1_bar',
                    ),
                ),
                       dict(
                id='vol2_id',
                status='vol2_status',
                size=1024,
                availabilityZone='vol2_availability',
                createdAt=datetime.datetime.now(),
                attachments=[dict(
                        id='vol2_id',
                        volumeId='vol2_id',
                        serverId='instance_uuid',
                        device='/foo2')],
                displayName='vol2_name',
                displayDescription='vol2_desc',
                volumeType='vol2_type',
                snapshotId='snap2_id',
                metadata=dict(
                    foo='vol2_foo',
                    bar='vol2_bar',
                    ),
                )]
        text = serializer.serialize(dict(volumes=raw_volumes), 'index')

        print text
        tree = etree.fromstring(text)

        self.assertEqual('volumes', tree.tag)
        self.assertEqual(len(raw_volumes), len(tree))
        for idx, child in enumerate(tree):
            self._verify_volume(raw_volumes[idx], child)
