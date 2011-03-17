import datetime as dt
import unittest

from nova.image import glance

class StubGlanceClient(object):

    def __init__(self, images):
        self.images = images

    def get_image_meta(self, id):
        return self.images[id]

    def get_images_detailed(self):
        return self.images.itervalues()

class TestGlance(unittest.TestCase):

    def setUp(self):
        self.client = StubGlanceClient(None)
        self.service = glance.GlanceImageService(self.client)

    def test_show_passes_through_to_client(self):
        self.client.images = {'xyz': "image"}
        self.assertEqual(self.service.show({}, 'xyz'), "image")

    def test_detail_passes_through_to_client(self):
        self.client.images = {1: "an image"}
        self.assertEqual(list(self.service.detail({})), ["an image"])

    def test_show_makes_create_datetimes(self):
        create_time = dt.datetime.utcnow()
        self.client.images = {'xyz': {
            'id': "id",
            'name': "my awesome image",
            'created_at': create_time.isoformat(),
        }}
        actual = self.service.show({}, 'xyz')
        self.assertEqual(actual['created_at'], create_time)

    def test_show_makes_update_datetimes(self):
        update_time = dt.datetime.utcnow()
        self.client.images = {'abc': {
            'id': "id",
            'name': "my okay image",
            'updated_at': update_time.isoformat(),
        }}
        actual = self.service.show({}, 'abc')
        self.assertEqual(actual['updated_at'], update_time)

    def test_show_makes_delete_datetimes(self):
        delete_time = dt.datetime.utcnow()
        self.client.images = {'123': {
            'id': "123",
            'name': "my lame image",
            'deleted_at': delete_time.isoformat(),
        }}
        actual = self.service.show({}, '123')
        self.assertEqual(actual['deleted_at'], delete_time)

    def test_show_handles_deleted_at_none(self):
        self.client.images = {'747': {
            'id': "747",
            'name': "not deleted",
            'deleted_at': None,
        }}
        actual = self.service.show({}, '747')
        self.assertEqual(actual['deleted_at'], None)

    def test_detail_handles_timestamps(self):
        now = dt.datetime.utcnow()
        image1 = {
            'id': 1,
            'name': 'image 1',
            'created_at': now.isoformat(),
            'updated_at': now.isoformat(),
            'deleted_at': None,
        }
        image2 = {
            'id': 2,
            'name': 'image 2',
            'deleted_at': now.isoformat(),
        }
        self.client.images = {1: image1, 2: image2}
        i1, i2 = self.service.detail({})
        self.assertEqual(i1['created_at'], now)
        self.assertEqual(i1['updated_at'], now)
        self.assertEqual(i1['deleted_at'], None)
        self.assertEqual(i2['deleted_at'], now)
