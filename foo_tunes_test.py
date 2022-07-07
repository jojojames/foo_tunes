import foo_tunes
import json
import os
import shutil
import unittest

from pathlib import Path

from foo_tunes import FFProbe, GenreChanger, Playlist, PlaylistManager, Resilio


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
        self.assertEqual(
            foo_tunes.flac_extension_to_alac(
                r'X:\music\K-Pop\TWICE\#TWICE\08 TT.FLAC'),
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

    def test_get_playlist_write_path(self):
        self.assertEqual(
            foo_tunes.get_playlist_write_path('/', '~/file.m3u'),
            Path('/file.m3u'))
        self.assertEqual(
            foo_tunes.get_playlist_write_path('/a/b/c', '~/file.m3u'),
            Path('/a/b/c/file.m3u'))
        self.assertEqual(
            foo_tunes.get_playlist_write_path('~/a/b/c', '~/file.m3u'),
            Path('~/a/b/c/file.m3u'))
        self.assertEqual(
            foo_tunes.get_playlist_write_path(None, '~/file.m3u'),
            Path('~/file.m3u'))
        self.assertEqual(
            foo_tunes.get_playlist_write_path('/a/b/c', '~/file.m3u', '_'),
            Path('/a/b/c/_file.m3u'))

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

    def test_temp_path_from_path(self):
        self.assertEqual(
            foo_tunes.temp_path_from_path('/a/b/c/abc.mp3'),
            '/a/b/c/abc_temp.mp3')

    def test_find_flac_files(self):
        temp_dir = os.path.join(os.path.dirname(__file__), 'testdata/temp_dir')
        os.mkdir(temp_dir)

        files = [
            os.path.join(temp_dir, 'a.mp3'),
            os.path.join(temp_dir, 'a.flac'),
            os.path.join(temp_dir, 'a.m4a'),
            os.path.join(temp_dir, 'a.not')
        ]

        for file in files:
            with open(file, 'w') as f:
                f.write('Create a new text file!')

        # One flac file is in the list of four.
        self.assertEqual(len(foo_tunes.find_flac_files(temp_dir)), 1)

        # Clean up test directory.
        shutil.rmtree(temp_dir)

    def test_find_all_music_files(self):
        temp_dir = os.path.join(os.path.dirname(__file__), 'testdata/temp_dir')
        os.mkdir(temp_dir)

        files = [
            os.path.join(temp_dir, 'a.mp3'),
            os.path.join(temp_dir, 'a.flac'),
            os.path.join(temp_dir, 'a.m4a'),
            os.path.join(temp_dir, 'a.not')
        ]

        for file in files:
            with open(file, 'w') as f:
                f.write('Create a new text file!')

        # Find three files even though files is a list of four.
        self.assertEqual(len(foo_tunes.find_all_music_files(temp_dir)), 3)

        # Clean up test directory.
        shutil.rmtree(temp_dir)

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

        ds_store_file = os.path.join(flac_dir, r'.DS_Store')
        with open(ds_store_file, 'w') as f:
            f.write('Create a new text file!')

        self.assertEqual(len(os.listdir(flac_dir)), 2)

        foo_tunes.delete_some_trash(flac_dir)

        # Assert trash has been deleted.
        self.assertEqual(len(os.listdir(flac_dir)), 1)


class FFProbeTest(unittest.TestCase):

    # Generated with:
    # ffprobe testdata/music/sample-3s.mp3 -v quiet -print_format json \
    # -show_format -show_streams -hide_banner
    FFPROBE_RESULT = '''
{
    "streams": [
        {
            "index": 0,
            "codec_name": "mp3",
            "codec_long_name": "MP3 (MPEG audio layer 3)",
            "codec_type": "audio",
            "codec_tag_string": "[0][0][0][0]",
            "codec_tag": "0x0000",
            "sample_fmt": "fltp",
            "sample_rate": "44100",
            "channels": 2,
            "channel_layout": "stereo",
            "bits_per_sample": 0,
            "r_frame_rate": "0/0",
            "avg_frame_rate": "0/0",
            "time_base": "1/14112000",
            "start_pts": 353600,
            "start_time": "0.025057",
            "duration_ts": 45711360,
            "duration": "3.239184",
            "bit_rate": "128000",
            "disposition": {
                "default": 0,
                "dub": 0,
                "original": 0,
                "comment": 0,
                "lyrics": 0,
                "karaoke": 0,
                "forced": 0,
                "hearing_impaired": 0,
                "visual_impaired": 0,
                "clean_effects": 0,
                "attached_pic": 0,
                "timed_thumbnails": 0,
                "captions": 0,
                "descriptions": 0,
                "metadata": 0,
                "dependent": 0,
                "still_image": 0
            },
            "tags": {
                "encoder": "Lavc57.10"
            }
        }
    ],
    "format": {
        "filename": "sample-3s.mp3",
        "nb_streams": 1,
        "nb_programs": 0,
        "format_name": "mp3",
        "format_long_name": "MP2/3 (MPEG audio layer 2/3)",
        "start_time": "0.025057",
        "duration": "3.239184",
        "size": "52304",
        "bit_rate": "129178",
        "probe_score": 51,
        "tags": {
            "genre": "Test",
            "encoder": "Lavf59.16.100"
        }
    }
}
    '''

    def test_get_genre(self):
        music_file = os.path.join(os.path.dirname(__file__),
                                  'testdata/music/sample-3s.mp3')
        probe = FFProbe(input_file=music_file)
        # Don't actually process the file, load a string already generated
        # from the same file instead to avoid the call to ffprobe.
        probe.result = json.loads(FFProbeTest.FFPROBE_RESULT)
        self.assertEqual(probe.get_genre(), 'Test')

    def test_get_genre_tag(self):
        music_file = os.path.join(os.path.dirname(__file__),
                                  'testdata/music/sample-3s.mp3')
        probe = FFProbe(input_file=music_file)
        # Don't actually process the file, load a string already generated
        # from the same file instead to avoid the call to ffprobe.
        probe.result = json.loads(FFProbeTest.FFPROBE_RESULT)
        self.assertEqual(probe.get_genre_tag(), 'genre')


class GenreChangerTest(unittest.TestCase):
    def test_find_appropriate_genre(self):
        g = GenreChanger(input_dir='unused')
        self.assertEqual(g.find_appropriate_genre('AlternRock'),
                         'Alternative Rock')
        self.assertEqual(g.find_appropriate_genre('soundtrack'),
                         'OST')
        self.assertEqual(g.find_appropriate_genre('rock'),
                         'Rock')
        self.assertEqual(g.find_appropriate_genre('alternative rock'),
                         'Alternative Rock')
        self.assertEqual(g.find_appropriate_genre('Alternative rock'),
                         'Alternative Rock')
        self.assertEqual(g.find_appropriate_genre('Hip-hop'),
                         'Hip-Hop')
        self.assertEqual(g.find_appropriate_genre('j-pop'),
                         'J-Pop')
        self.assertEqual(g.find_appropriate_genre('k-pop'),
                         'K-Pop')


class PlaylistManagerTest(unittest.TestCase):
    def test_should_manage_playlist(self):
        deny_list = [
            'ALAC',
            'Auto -',
            'Filter Results',
            'FLAC',
            'Library',
            'LOSSLESS',
            'LOSSY',
            'TODO_',
            'TO_PROCESS',
            'i_1',
            'i_2',
        ]

        p = PlaylistManager(input_dir="doesnt_matter",
                            output_dir="doesnt matter",
                            deny_list=deny_list)

        deny_playlists = [
            '/Volumes/bebe/playlists/windows/TO_PROCESS.m3u8',
            '/Volumes/bebe/playlists/windows/_TO_PROCESS.m3u8',
            '/Volumes/bebe/playlists/windows/ALAC.m3u8',
            '/Volumes/bebe/playlists/windows/Auto - Most Played.m3u8',
            '/Volumes/bebe/playlists/windows/Auto - Replay Gain Missing.m3u8',
            '/Volumes/bebe/playlists/windows/Filter Results.m3u8',
            '/Volumes/bebe/playlists/windows/Filter Results (Playback).m3u8',
            '/Volumes/bebe/playlists/windows/FLAC.m3u8',
            '/Volumes/bebe/playlists/windows/i_1.m3u8',
            '/Volumes/bebe/playlists/windows/i_2.m3u8',
            '/Volumes/bebe/playlists/windows/Library.m3u8',
            '/Volumes/bebe/playlists/windows/Library Viewer Selection.m3u8',
            '/Volumes/bebe/playlists/windows/LOSSLESS.m3u8',
            '/Volumes/bebe/playlists/windows/LOSSY.m3u8',
            '/Volumes/bebe/playlists/windows/TODO_J.m3u8',
            '/Volumes/bebe/playlists/windows/TODO_Indie.m3u8'
        ]

        for deny in deny_playlists:
            playlist: Playlist = Playlist(file=deny)
            self.assertFalse(p.should_manage_playlist(playlist=playlist),
                             msg=playlist.file)

        accept_playlists = [
            '/Volumes/bebe/playlists/windows/2009 - 2011.m3u8',
            '/Volumes/bebe/playlists/windows/2012 - 2013.m3u8',
            '/Volumes/bebe/playlists/windows/2014 - 2019.m3u8',
            '/Volumes/bebe/playlists/windows/2020 - 2021.m3u8',
            '/Volumes/bebe/playlists/windows/Acid Jazz.m3u8',
            '/Volumes/bebe/playlists/windows/COALS.m3u8',
            '/Volumes/bebe/playlists/windows/Concentratre.m3u8',
            '/Volumes/bebe/playlists/windows/C-Pop.m3u8',
            '/Volumes/bebe/playlists/windows/Dance.m3u8',
            '/Volumes/bebe/playlists/windows/EDM.m3u8',
            '/Volumes/bebe/playlists/windows/Folk.m3u8',
            '/Volumes/bebe/playlists/windows/Genki Playlist.m3u8',
            '/Volumes/bebe/playlists/windows/Hip Hop.m3u8',
            '/Volumes/bebe/playlists/windows/Indie.m3u8',
            '/Volumes/bebe/playlists/windows/JAZZ.m3u8',
            '/Volumes/bebe/playlists/windows/J-Pop.m3u8',
            '/Volumes/bebe/playlists/windows/KOSTS.m3u8',
            '/Volumes/bebe/playlists/windows/K-Pop.m3u8',
            '/Volumes/bebe/playlists/windows/Listening Practice.m3u8',
            '/Volumes/bebe/playlists/windows/Mellow.m3u8',
            '/Volumes/bebe/playlists/windows/No Voice.m3u8',
            '/Volumes/bebe/playlists/windows/POP.m3u8',
            '/Volumes/bebe/playlists/windows/PUBG.m3u8',
            '/Volumes/bebe/playlists/windows/Punk & SKA.m3u8',
            '/Volumes/bebe/playlists/windows/RANDOM.m3u8',
            '/Volumes/bebe/playlists/windows/RnB.m3u8',
            '/Volumes/bebe/playlists/windows/Rock.m3u8',
            '/Volumes/bebe/playlists/windows/Setlist - GFRIEND Yokohama.m3u8',
            '/Volumes/bebe/playlists/windows/Setlist - TWICE LA.m3u8',
            '/Volumes/bebe/playlists/windows/Setlist - TWICE Miyagi.m3u8',
            '/Volumes/bebe/playlists/windows/Soul.m3u8',
            '/Volumes/bebe/playlists/windows/Upbeat Uplifting.m3u8',
            '/Volumes/bebe/playlists/windows/Voice.m3u8',
            '/Volumes/bebe/playlists/windows/_Zero.m3u8'
        ]

        for accept in accept_playlists:
            playlist: Playlist = Playlist(file=accept)
            self.assertTrue(p.should_manage_playlist(playlist),
                            msg=playlist.file)


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

        not_sync_file = os.path.join(sync_dir, '.sync/abc.sync')
        with open(not_sync_file, 'w') as f:
            f.write('Create a new text file!')

        self.assertFalse(resilio.syncing())

        sync_file = os.path.join(sync_dir, '.sync/abc.!.sync')
        with open(sync_file, 'w') as f:
            f.write('Create a new text file!')

        self.assertTrue(resilio.syncing())

        # Clean up the files that we just created.
        os.remove(not_sync_file)
        os.remove(sync_file)


if __name__ == '__main__':
    foo_tunes.VERBOSE = True
    foo_tunes.DRY = False
    unittest.main()
