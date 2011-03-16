import unittest

from nova.image import glance

class StubGlanceClient(object):

    def __init__(self, images):
        self._images = images

    def get_image_meta(id):
        return self._images[id]

class TestGlance(unittest.TestCase):

    def test(self):
        images = {'xyz': "image"}
        client = StubGlanceClient(images)
        service = glance.GlanceImageService(client)
