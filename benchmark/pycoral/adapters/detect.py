"""Minimal mock of pycoral.adapters.detect for CPU benchmark."""
import collections


class BBox(collections.namedtuple('BBox', ['xmin', 'ymin', 'xmax', 'ymax'])):
    __slots__ = ()

    @property
    def width(self):
        return self.xmax - self.xmin

    @property
    def height(self):
        return self.ymax - self.ymin

    def scale(self, sx, sy):
        return BBox(
            xmin=sx * self.xmin,
            ymin=sy * self.ymin,
            xmax=sx * self.xmax,
            ymax=sy * self.ymax,
        )


Object = collections.namedtuple('Object', ['id', 'score', 'bbox'])
