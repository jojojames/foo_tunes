import os
import foo_tunes
import unittest

from pathlib import Path

from foo_tunes import Resilio


class FooTunesTest(unittest.TestCase):

    def test_true_path(self):
        self.assertEqual(foo_tunes.true_path('~/abc'),
                         os.path.join(os.path.expanduser('~'), 'abc'))
        self.assertEqual(foo_tunes.true_path('/a/b/c'),
                         '/a/b/c')
        self.assertEqual(foo_tunes.true_path('/a/b/c/'),
                         '/a/b/c')

    def test_flac_extension_to_alac(self):
        self.assertEqual(
            foo_tunes.flac_extension_to_alac(
                r'X:\music\K-Pop\LOOΠΔ\[#]\04 Oh (Yes I Am).flac'),
            r'X:\music\K-Pop\LOOΠΔ\[#]\04 Oh (Yes I Am).m4a')
        self.assertEqual(
            foo_tunes.flac_extension_to_alac(
                r'X:\music\K-Pop\TWICE\#TWICE\08 TT.Flac'),
            r'X:\music\K-Pop\TWICE\#TWICE\08 TT.m4a')

    def test_windows_path_to_posix(self):
        self.assertEqual(
            foo_tunes.windows_path_to_posix(
                r'X:\music\K-Pop\TWICE\#TWICE\10 SIGNAL.m4a'),
            r'X:/music/K-Pop/TWICE/#TWICE/10 SIGNAL.m4a')

        self.assertEqual(
            foo_tunes.windows_path_to_posix(
                r'X:\music\K-Pop\GFRIEND\Parallel\06 빨간우산 (RED UMBRELLA).m4a'),
            r'X:/music/K-Pop/GFRIEND/Parallel/06 빨간우산 (RED UMBRELLA).m4a')

    def test_get_write_path(self):
        self.assertEqual(
            foo_tunes.get_write_path('/', '~/file.m3u'), Path('/file.m3u'))
        self.assertEqual(
            foo_tunes.get_write_path('/a/b/c', '~/file.m3u'),
            Path('/a/b/c/file.m3u'))
        self.assertEqual(
            foo_tunes.get_write_path('~/a/b/c', '~/file.m3u'),
            Path('~/a/b/c/file.m3u'))
        self.assertEqual(
            foo_tunes.get_write_path(None, '~/file.m3u'), Path('~/file.m3u'))

    def test_from_str_to_str(self):
        self.assertEqual(
            foo_tunes.from_str_to_str(
                r'X:/music/K-Pop/Younha/Cover/Gee.mp3',
                r'X:/music',
                r'/Users/james/Music'),
            r'/Users/james/Music/K-Pop/Younha/Cover/Gee.mp3')

    def test_alac_path_from_flac_path(self):
        self.assertEqual(
            foo_tunes.alac_path_from_flac_path('~/a.flac'), '~/a.m4a')
        self.assertEqual(
            foo_tunes.alac_path_from_flac_path('/a/b/c.flac'), '/a/b/c.m4a')

    def test_delete_some_trash(self):
        flac_dir = os.path.join(os.path.dirname(__file__), 'testdata/flac_dir')

        self.assertEqual(len(os.listdir(flac_dir)), 1)

        foo_tunes.delete_some_trash(flac_dir)

        # Assert nothing has been deleted because the current directory has no
        # trash in it.
        self.assertEqual(len(os.listdir(flac_dir)), 1)

        trash_file = os.path.join(flac_dir, r'._01 Next Level.flac')
        with open(trash_file, 'w') as f:
            f.write('Create a new text file!')
        self.assertEqual(len(os.listdir(flac_dir)), 2)

        foo_tunes.delete_some_trash(flac_dir)

        # Assert trash has been deleted.
        self.assertEqual(len(os.listdir(flac_dir)), 1)


class ResilioTest(unittest.TestCase):
    def test_get_temp_directory(self):
        self.assertEqual(
            Resilio('/bebe/sync/').get_temp_directory(),
            '/bebe/sync/.sync')
        self.assertEqual(
            Resilio('/bebe/sync').get_temp_directory(),
            '/bebe/sync/.sync')

    def test_syncing(self):
        sync_dir = os.path.join(os.path.dirname(__file__), 'testdata/sync')

        resilio: Resilio = Resilio(sync_dir=sync_dir)
        self.assertFalse(resilio.syncing())

        sync_file = os.path.join(sync_dir, '.sync/abc.!.sync')
        with open(sync_file, 'w') as f:
            f.write('Create a new text file!')
        self.assertTrue(resilio.syncing())

        # Clean up file that we just created.
        os.remove(sync_file)


if __name__ == '__main__':
    foo_tunes.VERBOSE = True
    foo_tunes.DRY = False
    foo_tunes.MP4ART_AVAILABLE = True
    unittest.main()
