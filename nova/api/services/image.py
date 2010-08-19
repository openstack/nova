import cPickle as pickle
import os.path
import string

class ImageService(object):
    """Provides storage and retrieval of disk image objects."""

    @staticmethod
    def load():
        """Factory method to return image service."""
        #TODO(gundlach): read from config.
        class_ = LocalImageService
        return class_()

    def index(self):
        """
        Return a list of image data dicts.  Each dict will contain an
        id key whose value is an opaque image id.
        """

    def show(self, id):
        """
        Returns a dict containing image data for the given opaque image id.
        """


class GlanceImageService(ImageService):
    """Provides storage and retrieval of disk image objects within Glance."""
    # TODO(gundlach): once Glance has an API, build this.
    pass


class LocalImageService(ImageService):
    """Image service storing images to local disk."""

    def __init__(self):
        self._path = "/tmp/nova/images"
        try:
            os.makedirs(self._path)
        except OSError: # exists
            pass

    def _path_to(self, image_id=''):
        return os.path.join(self._path, image_id)

    def _ids(self):
        """The list of all image ids."""
        return os.path.listdir(self._path)

    def index(self):
        return [ self.show(id) for id in self._ids() ]

    def show(self, id):
        return pickle.load(open(self._path_to(id))) 

    def create(self, data):
        """
        Store the image data and return the new image id.
        """
        id = ''.join(random.choice(string.letters) for _ in range(20))
        self.update(id, data)
        return id

    def update(self, image_id, data):
        """Replace the contents of the given image with the new data."""
        pickle.dump(data, open(self._path_to(image_id), 'w'))

    def delete(self, image_id):
        """
        Delete the given image.  Raises OSError if the image does not exist.
        """
        os.unlink(self._path_to(image_id))
