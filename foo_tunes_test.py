import foo_tunes
import unittest

from pathlib import Path

class FooTunesTest(unittest.TestCase):

    def test_flac_extension_to_alac(self):
        self.assertEqual(
            foo_tunes.flac_extension_to_alac(
                r'X:\music\K-Pop\LOOΠΔ\[#]\04 Oh (Yes I Am).flac'),
            r'X:\music\K-Pop\LOOΠΔ\[#]\04 Oh (Yes I Am).m4a')
        self.assertEqual(
            foo_tunes.flac_extension_to_alac(
                r'X:\music\K-Pop\TWICE\#TWICE\08 TT.Flac'),
            r'X:\music\K-Pop\TWICE\#TWICE\08 TT.m4a')

    def test_get_write_path(self):
        self.assertEqual(
            foo_tunes.get_write_path("/", "~/file.m3u"), Path("/file.m3u"))
        self.assertEqual(
            foo_tunes.get_write_path("/a/b/c", "~/file.m3u"),
            Path("/a/b/c/file.m3u"))
        self.assertEqual(
            foo_tunes.get_write_path("~/a/b/c", "~/file.m3u"),
            Path("~/a/b/c/file.m3u"))
        self.assertEqual(
            foo_tunes.get_write_path(None, "~/file.m3u"), Path("~/file.m3u"))

    # def test_upper(self):
    #     self.assertEqual('foo'.upper(), 'FOO')

    # def test_isupper(self):
    #     self.assertTrue('FOO'.isupper())
    #     self.assertFalse('Foo'.isupper())

    # def test_split(self):
    #     s = 'hello world'
    #     self.assertEqual(s.split(), ['hello', 'world'])
    #     # check that s.split fails when the separator is not a string
    #     with self.assertRaises(TypeError):
    #         s.split(2)

if __name__ == '__main__':
    unittest.main()
