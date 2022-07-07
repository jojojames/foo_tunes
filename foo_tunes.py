#!/usr/bin/python3

import argparse
import json
import glob
import platform
import queue
import re
import subprocess
import threading
import time
import traceback
import os

from datetime import datetime
from functools import partial
from pathlib import Path, PureWindowsPath
from shutil import move, rmtree, which
from typing import Any, Dict, List, Optional, Text
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


parser = argparse.ArgumentParser(description='Foobar2000 -> iTunes utilities')

# Playlist / .m3u8 Management

parser.add_argument(
    '-m3u_i',
    '--m3u_input_dir',
    help='Directory containing playlists/.m3u8 files to convert fron.')

parser.add_argument(
    '-m3u_o',
    '--m3u_output_dir',
    default=None,
    help='Directory containing converted playlists/.m3u8 files.')

parser.add_argument(
    '--m3u_flac_to_alac',
    default=False,
    action='store_true',
    help='Change .flac extension to .m4a in playlists.')

parser.add_argument(
    '--m3u_windows_to_posix',
    default=False,
    action='store_true',
    help='Convert music paths in playlist to posix format.')

parser.add_argument('--m3u_from_str',
                    help='String in playlist line to replace.')

parser.add_argument('--m3u_to_str',
                    help='String in playlist line to replace to.')

parser.add_argument(
    '--m3u_watch',
    default=False,
    action='store_true',
    help='If set, watch input directory for playlist changes and automatically'
    ' convert playlists in that directory using the related -m3u flags.')

# FLAC Conversion

parser.add_argument(
    '--flac_dir',
    help='If set, convert .flac files in this directory to .m4a.')

parser.add_argument(
    '--flac_overwrite_output', default=False, action='store_true',
    help='If set, always write/overwrite output files'
    ' when converting.')

parser.add_argument(
    '--flac_delete_original', default=False, action='store_true',
    help='If set, delete .flac version after converting to alac.')

parser.add_argument('--flac_threads', default=4, type=int,
                    help='Number of threads to use when converting.')

parser.add_argument(
    '--flac_watch',
    default=False,
    action='store_true',
    help='If set, watch input directory for flac changes and automatically '
    'convert flacs in that directory using the related -flac flags.')

parser.add_argument('--flac_change_genres', default=False, action='store_true',
                    help='If set, tweak genre tags to a common set of tags'
                    ' after converting encoding music files. Genres tagged '
                    ' will be the list of music files in --flac_dir, even'
                    ' if the file isn\' a FLAC file.')

# Changing Metadata / Tags

parser.add_argument('--change_genres', default=False, action='store_true',
                    help='If set, tweak genre tags to a common set of tags'
                    ' in --flac_dir. If this is set, changing tags is the '
                    ' only thing this utility does.')

# Watching for Changes

parser.add_argument(
    '--watch_sleep_time', default=30, type=int,
    help='Number of seconds to sleep for when watching directory changes.')

parser.add_argument(
    '--watch_playlist_delay', default=20, type=int,
    help='Number of seconds to wait before managing playlists upon directory'
    ' changes.')

parser.add_argument(
    '--watch_convert_delay', default=120, type=int,
    help='Number of seconds to wait before converting flacs upon directory'
    ' changes.')

# Utility

parser.add_argument('--clean_up',
                    help='If set, clean up this directory of extraneous files.'
                    'This is of the form --clean_up=/some/directory')

parser.add_argument('--dry', default=False, action='store_true',
                    help='If set, don\'t write any new changes.')

parser.add_argument('--jojo', default=False, action='store_true',
                    help='If set, manage music.')

parser.add_argument('-v', '--verbose', default=False, action='store_true',
                    help='Verbose logging.')


def print_if(str: str) -> None:
    """Print statement only if VERBOSE or DRY is set."""
    if VERBOSE or DRY:
        print(str)


def true_path(path: str) -> Optional[str]:
    # https://stackoverflow.com/questions/37863476/why-would-one-use-both-os-path-abspath-and-os-path-realpath
    if path is None:
        return None
    return os.path.realpath(os.path.expanduser(path))


def flac_extension_to_alac(song: str) -> str:
    pattern = re.compile(r'.flac', re.IGNORECASE)
    return pattern.sub('.m4a', song)


def windows_path_to_posix(song: str) -> str:
    return str(PureWindowsPath(song).as_posix())


def get_playlist_write_path(m3u_output_dir: str,
                            file: str,
                            prefix: Optional[str] = None) -> Path:
    base_name = os.path.basename(file)
    if prefix:
        base_name = prefix + base_name

    if m3u_output_dir:
        playlist_path = os.path.normpath(os.path.join(m3u_output_dir,
                                                      base_name))
    else:
        playlist_path = os.path.normpath(os.path.join(os.path.dirname(file),
                                                      base_name))
    return Path(playlist_path)


def from_str_to_str(song: str, from_str: str, to_str: str) -> str:
    return song.replace(from_str, to_str)


def alac_path_from_flac_path(flac_path: str) -> Text:
    directory, file_name = os.path.split(flac_path)
    base_name, extension = os.path.splitext(file_name)
    alac_path = os.path.join(directory, base_name + '.m4a')
    return alac_path


def temp_path_from_path(path: str) -> Text:
    """Returns a filepath that mirrors path but with _temp suffixed to it."""
    directory, file_name = os.path.split(path)
    base_name, extension = os.path.splitext(file_name)
    new_path = os.path.join(directory, base_name + '_temp' + extension)
    return new_path


def walk_files(directory: str) -> List[str]:
    # https://stackoverflow.com/questions/19309667/recursive-os-listdir
    return [os.path.join(dp, f)
            for dp, dn, fn in os.walk(os.path.expanduser(directory))
            for f in fn]


def find_flac_files(directory: str) -> List[str]:
    files = walk_files(directory)

    flac_pattern = re.compile(r'.flac$', re.IGNORECASE)
    flac_files = []
    for f in files:
        if re.search(flac_pattern, f):
            flac_files.append(f)

    print_if(f'Found flac files: {flac_files}')
    return flac_files


def find_all_music_files(directory: str) -> List[str]:
    files = walk_files(directory=directory)

    music_pattern = re.compile(r'(.flac$|.mp3$|.m4a$)', re.IGNORECASE)
    music_files = []
    for f in files:
        if re.search(music_pattern, f):
            music_files.append(f)

    print_if(f'Found music files: {music_files}')
    return music_files


def delete_some_trash(directory: str) -> None:
    """Delete extraneous trash files that may corrupt entire process."""
    files = walk_files(directory)

    # E.g.
    # ._file.flac
    # /bebe/sync/music/._file.flac
    # .DS_Store
    resilio_trash_pattern = re.compile(r'(\._|^\._|\.DS_Store)')
    for f in files:
        print(f)
        if re.search(resilio_trash_pattern, f):
            print_if(f'Deleting trash {f}...')
            os.remove(f)


def delete_directory_if_exists(directory: str) -> None:
    if os.path.exists(directory):
        print_if(f'Deleting directory {directory}...')
        rmtree(directory)


def print_separator() -> None:
    if VERBOSE:
        print('--------------------------------------------------------------')


def print_json(obj) -> None:
    print(json.dumps(obj, indent=2))


def print_process_output(process, prefix: str) -> None:
    if not process:
        return

    if process.stdout and process.stdout.strip():
        print_if(f'{prefix}: stdout: {process.stdout}')
    if process.stderr and process.stderr.strip():
        print_if(f'{prefix}: stderr: {process.stderr}')


class Playlist:
    """Class representing an m3u playlist."""

    def __init__(self, file: str):
        self.file = file
        self.songs = None

    def read(self):
        if self.songs:
            return
        self.songs = []
        print_if(f'Reading file: {self.file}')
        with open(self.file, 'r') as f:
            for line in f.readlines():
                if line.strip():
                    self.songs.append(line.strip())

    def write(self, output_dir=None, prefix: Optional[str] = None):
        if not self.songs:
            self.read()

        playlist_path = get_playlist_write_path(m3u_output_dir=output_dir,
                                                file=self.file,
                                                prefix=prefix)
        playlist_path.parent.mkdir(exist_ok=True, parents=True)

        if not DRY:
            with open(playlist_path, 'w', encoding='utf8') as f:
                for each in self.songs:
                    f.write(each + '\n')

        print_if(f'Wrote {playlist_path}')


class PlaylistManager:
    """Class that manages reading and writing Playlists."""

    DEFAULT_DENY_LIST = [
        'ALAC',
        'Auto -',
        'Filter Results',
        'FLAC',
        'Library',
        'LOSSLESS',
        'LOSSY',
        'TODO',
        'TO_PROCESS',
        'i_1',
        'i_2',
    ]

    def __init__(self,
                 input_dir: str,
                 output_dir: str,
                 deny_list: List[str] = DEFAULT_DENY_LIST):
        self.input_dir = true_path(input_dir)
        self.output_dir = true_path(output_dir)
        self.playlists: List[Playlist] = []
        self.deny_list = deny_list

    def should_manage_playlist(self, playlist: Playlist):
        for deny in self.deny_list:
            deny_pattern = re.compile(deny)
            if re.search(deny_pattern, playlist.file):
                return False
        return True

    def read(self):
        playlist_glob = os.path.join(self.input_dir, '*.m3u8')
        print_if(f'Globbing for: {playlist_glob}')

        playlist_files = glob.glob(playlist_glob)
        for playlist_file in playlist_files:
            playlist: Playlist = Playlist(playlist_file)
            if self.should_manage_playlist(playlist):
                playlist.read()
                self.playlists.append(playlist)
            else:
                print_if(f'Skipped reading playlist: {playlist.file}...')

        print_if(f'Playlist Files: {playlist_files}')

    def write(self, prefix: Optional[str] = None):
        for playlist in self.playlists:
            playlist.write(self.output_dir, prefix=prefix)

    def convert_flac_to_alac(self):
        print_if('Converting m3u playlist extensions from .flac to .alac.')
        for playlist in self.playlists:
            playlist.songs = list(map(flac_extension_to_alac, playlist.songs))

    def convert_windows_to_posix(self):
        print_if('Converting m3u playlist from Windows to Posix.')
        for playlist in self.playlists:
            playlist.songs = list(map(windows_path_to_posix, playlist.songs))

    def convert_from_str_to_str(self, from_str: str, to_str: str):
        print_if(f'Converting m3u playlist from {from_str} to {to_str}.')

        # Create partial function with from_str and to_str already set.
        from_str_to_str_fn = partial(from_str_to_str,
                                     from_str=from_str, to_str=to_str)
        for playlist in self.playlists:
            playlist.songs = list(map(from_str_to_str_fn, playlist.songs))


class Resilio:
    def __init__(self, sync_dir: str):
        self.sync_dir = true_path(sync_dir)

    def get_temp_directory(self):
        """Returns the Resilio directory that contains temporary downloads."""
        return os.path.join(self.sync_dir, '.sync')

    def syncing(self):
        """Returns whether or not Resilio is currently syncing."""
        files = os.listdir(self.get_temp_directory())

        sync_pattern = re.compile(r'!.sync$')
        for file in files:
            print_if(f'Looking for sync pattern in {file}...')
            if re.search(sync_pattern, file):
                print_if(f'Found sync pattern {file}')
                return True
            else:
                print_if(f'Not a sync pattern {file}')

        return False


class FlacToAlacConverter:
    def __init__(self,
                 input_dir: str,
                 overwrite_output: bool,
                 delete_original: bool,
                 num_threads: int = 4):
        self.input_dir = true_path(input_dir)
        self.flacs = []
        self.queue = queue.Queue()
        self.threads = []
        self.thread_kill_event = threading.Event()
        self.overwrite_output = overwrite_output
        self.delete_original = delete_original
        self.num_threads = num_threads

    def read(self):
        print_if(f'Finding files recursive for: {self.input_dir}')

        # Clean up trash first...
        delete_some_trash(self.input_dir)

        flac_files = find_flac_files(self.input_dir)

        print_separator()
        print_if(f'# of Flac files to convert: {len(flac_files)}')
        print_if(f'Flac files to convert: {flac_files}')
        print_separator()

        self.flacs = flac_files

    def convert_worker(self):
        while not self.thread_kill_event.is_set():
            try:
                flac_path, alac_path = self.queue.get_nowait()
            except Exception:
                # Loop exits here when all threads exhaust self.queue.
                print('Exiting worker thread...')
                break

            print_separator()
            if os.path.exists(alac_path):
                if self.overwrite_output:
                    print_if(f'{alac_path} exists... deleting first...')
                    os.remove(alac_path)
                else:
                    print_if(f'{alac_path} already exists... skipping...')
                    continue

            print('Converting file {} of {}'.format(
                self.total_queue_size - self.queue.qsize(),
                self.total_queue_size), flush=True)
            print('From:', flac_path)
            print('To:', alac_path)
            print_separator()

            if XLD_AVAILABLE:
                # https://tmkk.undo.jp/xld/index_e.html
                # This seems to get all the metadata and the coverart but it's
                # OSX only...
                # brew install xld
                process = subprocess.run(
                    ['xld', flac_path, '-f', 'alac', '-o', alac_path],
                    capture_output=True, text=True)
            else:
                # Some metadata is lost doing this but using -movflags seems to
                # make the metadata unrecognizable by foobar2000, iTunes, etc.
                process = subprocess.run(
                    # https://unix.stackexchange.com/questions/415477/lossless-audio-conversion-from-flac-to-alac-using-ffmpeg
                    ['ffmpeg',
                     # https://superuser.com/questions/326629/how-can-i-make-ffmpeg-be-quieter-less-verbose
                     '-v', 'info' if VERBOSE else 'warning',
                     '-i', flac_path,  # input file
                     '-acodec', 'alac',  # 'force audio codec' to alac
                     '-vcodec', 'copy',  # 'force video codec' to copy stream
                     alac_path],  # 'output file'
                    # https://stackoverflow.com/questions/41171791/how-to-suppress-or-capture-the-output-of-subprocess-run
                    capture_output=True, text=True)

            prefix = 'xld' if XLD_AVAILABLE else 'ffmpeg'
            print_process_output(process, prefix=prefix)
            print_separator()

            # Should we try deleting even if we potentially skip converting?
            if self.delete_original:
                print_if(f'Deleting {flac_path}...')
                os.remove(flac_path)

    def write(self):
        if len(self.flacs) == 0:
            print_if('No flacs to convert... skipping.')
            return
        for flac_path in self.flacs:
            alac_path = alac_path_from_flac_path(flac_path=flac_path)
            self.queue.put((flac_path, alac_path))
            self.total_queue_size = self.queue.qsize()
        for i in range(self.num_threads):
            thread = threading.Thread(target=self.convert_worker)
            thread.start()
            self.threads.append(thread)
        for thread in self.threads:
            thread.join()


class FFProbe():
    def __init__(self, input_file: str):
        self.input_file = true_path(input_file)

    def get_genre(self) -> Optional[str]:
        """Returns the metadata field Genre in this input file."""
        tags = self.get_tags()
        if not tags:
            return None

        genre_tag = self.get_genre_tag()
        if not genre_tag:
            return None

        return tags[genre_tag]

    def get_genre_tag(self) -> Optional[str]:
        """Returns the tag name for Genre used in this input file."""
        if (tags := self.get_tags()) is not None:
            possible_genre_tags = ['Genre', 'GENRE', 'genre']
            for genre_tag in possible_genre_tags:
                if genre_tag in tags:
                    return genre_tag

        return None

    def get_tags(self) -> Optional[Dict[str, Any]]:
        """Get tags from ffprobe result."""
        if not self.result:
            return None

        if 'format' not in self.result:
            return None

        format = self.result['format']

        if 'tags' not in format:
            return None

        tags = format['tags']
        return tags

    def read(self):
        # https://ffmpeg.org/ffprobe.html
        # https://gist.github.com/nrk/2286511
        try:
            process = subprocess.run(
                ['ffprobe',
                 self.input_file,
                 '-v',
                 'quiet',
                 '-print_format',
                 'json',
                 '-show_format',
                 '-show_streams',
                 '-hide_banner'],
                capture_output=True, text=True)

            print_if(process.stderr)
            json_string = process.stdout
            ffprobe_result = json.loads(json_string)
            # print_json(ffprobe_result)
            self.result = ffprobe_result
            if (tags := self.get_tags()) is not None:
                print_separator()
                print_if(f'{self.input_file}:')
                print_json(tags)
                print_separator()
        except Exception:
            print('Exception calling ffprobe...')
            traceback.print_exc()


class GenreChanger():
    def __init__(self,
                 input_dir: str,
                 num_threads: int = 4):
        self.input_dir = true_path(input_dir)
        self.queue = queue.Queue()
        self.threads = []
        self.thread_kill_event = threading.Event()
        self.num_threads = num_threads

    def read(self):
        self.files = find_all_music_files(self.input_dir)

    def find_appropriate_genre(self, genre: Optional[str]) -> Optional[str]:
        if not genre:
            return None

        patterns: Dict = {
            '(alternrock)': 'Alternative Rock',
            '(kpop|korean)': 'K-Pop',
            '(cpop|chinese|cantonese|mandarin)': 'C-Pop',
            '(jpop|japanese)': 'J-Pop',
            '(rap)': 'Hip-Hop',
            # '(rock)': 'Rock',  # Don't do, clashes with Alternative Rock.
            '(soundtrack)': 'OST',
            '(vpop|vietnamese)': 'V-Pop'
        }

        for k, v in patterns.items():
            pattern = re.compile(k)
            if re.search(pattern, genre.lower()):
                return v

        # 'rock' -> 'Rock'
        # 'alternative rock' -> 'Alternative Rock'
        # 'Alternative rock' -> 'Alternative Rock'
        # 'Hip-hop' -> 'Hip-Hop'
        return genre.lower().title()

    def convert_worker(self):
        while not self.thread_kill_event.is_set():
            try:
                music_file = self.queue.get_nowait()
            except Exception:
                # Loop exits here when all threads exhaust self.queue.
                print('Exiting worker thread...')
                break

            ffprobe = FFProbe(input_file=music_file)
            ffprobe.read()

            genre_tag = ffprobe.get_genre_tag()
            if not genre_tag:
                print_if(f'{music_file}: no genre tag found... skipping.')
                continue

            genre = ffprobe.get_genre()
            if not genre:
                print_if(f'{music_file}: no genre found... skipping.')
                continue

            appropriate_genre = self.find_appropriate_genre(genre)
            if genre == appropriate_genre:
                print_if(f'{music_file}: genre {genre} is already correct...'
                         ' skipping.')
                continue

            print_separator()
            print('Tagging file {} of {}'.format(
                self.total_queue_size - self.queue.qsize(),
                self.total_queue_size), flush=True)
            print_separator()

            directory, file_name = os.path.split(music_file)
            base_name, extension = os.path.splitext(file_name)
            extension = extension.lower()
            print_if(f'Tagging file: {file_name}')

            if extension == '.m4a' or extension == '.mp3':
                if MP4TAGS_AVAILABLE and extension == '.m4a':
                    process = subprocess.run([
                        'mp4tags',
                        '-genre',
                        appropriate_genre,
                        music_file  # mp4tags can edit in place!
                    ], capture_output=True, text=True)
                    print_process_output(process, 'mp4tags')
                else:
                    # ffmpeg can't edit in place so convert to a temp location
                    # first.
                    temp_path = temp_path_from_path(music_file)
                    print_if(f'Tagging from {music_file} to temp file: '
                             f'{temp_path}...')
                    command = [
                        'ffmpeg',
                        '-y',
                        '-v', 'warning' if VERBOSE else 'warning',
                        '-i',
                        music_file,
                        '-metadata',
                        f'{genre_tag}={appropriate_genre}',
                        '-c', 'copy',
                        temp_path
                    ]
                    print_if(command)
                    process = subprocess.run(command,
                                             capture_output=True,
                                             text=True)

                    # Then move the temp file...
                    print_if(f'Removing {music_file}... ')
                    os.remove(music_file)
                    print_if(f'Moving {temp_path} to {music_file}...')
                    move(temp_path, music_file)
                    print_process_output(process, 'ffmpeg tag')

            if extension == '.flac':
                if not METAFLAC_AVAILABLE:
                    print('metaflac unavailable for tagging flac files.')
                    continue

                print_if(f'Removing tag {genre_tag} from {music_file}...')
                # metaflac doesn't seem to have 'replace' as functionality
                # so remove the tag first.
                process = subprocess.run([
                    'metaflac',
                    music_file,
                    f'--remove-tag={genre_tag}'
                ], capture_output=True, text=True)
                print_process_output(process, 'metaflac remove-tag')

                print_if(f'Setting tag {genre_tag}={appropriate_genre} to '
                         f'{music_file}...')
                process = subprocess.run([
                    'metaflac',
                    music_file,
                    f'--set-tag={genre_tag}={appropriate_genre}'
                ])
                print_process_output(process, 'metaflac set-tag')

            print_separator()

    def write(self):
        if len(self.files) == 0:
            print_if('No music files to tag... skipping.')
            return
        for f in self.files:
            self.queue.put(f)
            self.total_queue_size = self.queue.qsize()
        for i in range(self.num_threads):
            thread = threading.Thread(target=self.convert_worker)
            thread.start()
            self.threads.append(thread)
        for thread in self.threads:
            thread.join()


class WatchHandler(FileSystemEventHandler):
    """File System Watch Handler for flac->alac changes."""

    def __init__(self, fn, ob_name: str, delay: int = 120,):
        self.fn = fn
        # Two minutes by default.
        # Recommend to use a higher delay for more stability and a lower delay
        # for more responsiveness.
        self.delay = delay
        self.timer: threading.Timer = None
        self.ob_name = ob_name

    def on_any_event(self, event):
        print_if(f'WatchHandler: on_any_event: {event}!!')
        if event.event_type == 'created':
            print_if(f'{self.ob_name}: scheduling timer...')

            if self.timer:
                print_if('Canceling current timer and creating a new one...')
                self.timer.cancel()
                self.timer = threading.Timer(self.delay, self.fn)
            else:
                print_if('Creating a new timer...')
                self.timer = threading.Timer(self.delay, self.fn)

            # Schedule timer to start.
            print_if(f'Timer scheduled to start in {self.delay} seconds...')
            self.timer.start()


class JojoMusicManager:
    def __init__(self, args):
        self.args = args

        self.resilio = Resilio(sync_dir=self.get_sync_directory())

        self.playlist_manager = PlaylistManager(
            input_dir=self.get_windows_m3u_directory(),
            output_dir=self.get_alac_m3u_directory())

        self.converter = FlacToAlacConverter(
            input_dir=self.get_flac_directory(),
            overwrite_output=True,
            delete_original=True)

    def get_playlist_directory(self):
        if platform.system() == 'Windows':
            return r'X:\playlists'
        if platform.system() == 'Darwin':
            return r'/Volumes/bebe/playlists'
        if platform.system() == 'FreeBSD':
            return r'/bebe/playlists'

    def get_windows_m3u_directory(self):
        return os.path.join(self.get_playlist_directory(), 'windows')

    def get_alac_m3u_directory(self):
        return os.path.join(self.get_playlist_directory(), 'alac')

    def get_osx_m3u_directory(self):
        return os.path.join(self.get_playlist_directory(), 'osx')

    def get_bsd_m3u_directory(self):
        return os.path.join(self.get_playlist_directory(), 'bsd')

    def get_sync_directory(self):
        if platform.system() == 'Windows':
            return r'X:\sync'
        if platform.system() == 'Darwin':
            return r'/Volumes/bebe/sync'
        if platform.system() == 'FreeBSD':
            return r'/bebe/sync'

    def get_flac_directory(self):
        if platform.system() == 'Windows':
            return r'X:\sync\flacsfor.me'
        if platform.system() == 'Darwin':
            return r'/Volumes/bebe/sync/flacsfor.me'
        if platform.system() == 'FreeBSD':
            return r'/bebe/sync/flacsfor.me'

    def get_music_directory(self):
        if platform.system() == 'Windows':
            return r'X:\music'
        if platform.system() == 'Darwin':
            return r'/Volumes/bebe/music'
        if platform.system() == 'FreeBSD':
            return r'/bebe/music'

    def convert_playlists(self):
        start = time.process_time()
        # Modify Foobar2000 m3u playlists with .flac entries to .alac.
        delete_directory_if_exists(self.get_alac_m3u_directory())
        self.playlist_manager.output_dir = self.get_alac_m3u_directory()
        self.playlist_manager.read()
        self.playlist_manager.convert_flac_to_alac()
        print_if(f'flac->alac, elapsed: {time.process_time() - start}')
        self.playlist_manager.write()

        # Write the OSX version deriving from the current list of playlists.
        delete_directory_if_exists(self.get_osx_m3u_directory())
        self.playlist_manager.output_dir = self.get_osx_m3u_directory()
        self.playlist_manager.convert_windows_to_posix()
        print_if(f'windows->posix, elapsed: {time.process_time() - start}')

        self.playlist_manager.convert_from_str_to_str(
            from_str=r'X:/music', to_str=r'/Users/james/Music')
        print_if(f'X:/music->/Users/james/Music, elapsed: '
                 f'{time.process_time() - start}')

        # Apple Music has random playlists loaded from Music Library.
        # Prefix the playlist with _ to get it sorted to the top.
        self.playlist_manager.write(prefix='_')

        # Write the FreeBSD version deriving from the current set of playlists.
        delete_directory_if_exists(self.get_bsd_m3u_directory())
        self.playlist_manager.output_dir = self.get_bsd_m3u_directory()
        self.playlist_manager.convert_from_str_to_str(
            from_str=r'/Users/james/Music', to_str=r'/bebe/music')
        print_if(f'/Users/james/Music->/bebe/music, elapsed: '
                 f'{time.process_time() - start}')

        self.playlist_manager.write()

    def convert_and_move_flacs(self):
        flac_dir = self.get_flac_directory()
        if not os.path.exists(flac_dir):
            print(f'{flac_dir} does not exist. Skipping convert and move...')
            return

        if self.resilio.syncing():
            print('Resilio syncing... Skipping flac conversion...')
            return

        # Get list of directories to move that aren't hidden.
        music_dirs = [f for f in os.listdir(flac_dir) if not f.startswith('.')]
        if len(music_dirs) == 0:
            print('No music directories to convert or move. Skipping.')
            return

        # Attempt to convert FLACs to ALACs.
        print('Attempting flac conversion...')
        try:
            self.converter.read()
            self.converter.write()
            print('Finished converting...')
            genre_changer = GenreChanger(flac_dir)
            genre_changer.read()
            genre_changer.write()
            print('Finished tagging...')
        except KeyboardInterrupt:
            if self.converter:
                self.converter.thread_kill_event.set()

            print('Done...')
        except Exception:
            print('Exception while converting music...')
            traceback.print_exc()

        try:
            # Move music to Music directory.
            move_to = os.path.join(self.get_music_directory(), '_TO_PROCESS')
            if not os.path.exists(move_to):
                os.makedirs(move_to)

            print_if(f'Music directories to move {music_dirs}')
            ds_store_pattern = re.compile(r'.DS_Store')
            for music_dir in music_dirs:
                if re.search(ds_store_pattern, music_dir):
                    continue
                from_dir = os.path.join(flac_dir, music_dir)
                to_dir = os.path.join(move_to, music_dir)
                print_if(f'Attempting to move {from_dir} to {to_dir}')
                move(from_dir, to_dir)
                print_if(f'Moved {from_dir} to {to_dir}...')
        except KeyboardInterrupt:
            print('Done...')
        except Exception:
            print('Exception while moving music...')
            traceback.print_exc()

    def setup_file_watchers(self):
        self.observers: List[Observer] = []

        self.playlist_observer = Observer()
        self.playlist_observer.schedule(
            WatchHandler(fn=self.convert_playlists,
                         ob_name='Playlist Observer',
                         delay=self.args.watch_playlist_delay),
            self.get_windows_m3u_directory(),
            recursive=False)
        print_if('Will start observer with name: Playlist Observer...')
        self.observers.append(self.playlist_observer)

        self.converter_observer = Observer()
        self.converter_observer.schedule(
            WatchHandler(fn=self.convert_and_move_flacs,
                         ob_name='FLAC Observer',
                         delay=self.args.watch_convert_delay),
            self.get_flac_directory(),
            recursive=False)
        print_if('Will start observer with name: FLAC Observer...')
        self.observers.append(self.converter_observer)

        for observer in self.observers:
            observer.start()

        try:
            while True:
                now = datetime.now()
                current_time = now.strftime('%H:%M:%S')
                print_if(f'Time: {current_time}.. Observing changes...')
                time.sleep(self.args.watch_sleep_time)
        except KeyboardInterrupt:
            print('User triggered abort.')
        except Exception:
            print('Exception while observing...')
            traceback.print_exc()
        finally:
            for observer in self.observers:
                observer.stop()
                observer.join()

    def run(self):
        self.convert_playlists()
        self.convert_and_move_flacs()
        self.setup_file_watchers()


class MusicManager:
    def __init__(self, args):
        self.args = args

    def run(self):
        if (not self.args.m3u_flac_to_alac and
                not self.args.m3u_windows_to_posix and
                not self.args.flac_dir):
            print('Need to specify action... e.g. --m3u_flac_to_alac')
            return
        self.convert_playlists()
        self.convert_flacs()
        self.watch()

    def convert_playlists(self):
        m3u_flac_to_alac = self.args.m3u_flac_to_alac
        m3u_windows_to_posix = self.args.m3u_windows_to_posix
        m3u_from_str = self.args.m3u_from_str
        m3u_to_str = self.args.m3u_to_str
        m3u_input_dir = self.args.m3u_input_dir
        m3u_output_dir = self.args.m3u_output_dir

        if (m3u_flac_to_alac or m3u_windows_to_posix or
                (m3u_from_str and m3u_to_str)):
            if not m3u_input_dir:
                print('Specify --m3u_input_dir...')
                return
            playlist_manager = PlaylistManager(input_dir=m3u_input_dir,
                                               output_dir=m3u_output_dir)
            try:
                start = time.process_time()
                playlist_manager.read()
                if m3u_flac_to_alac:
                    playlist_manager.convert_flac_to_alac()
                    print_if(
                        f'flac->alac, elapsed: {time.process_time() - start}')

                if m3u_windows_to_posix:
                    playlist_manager.convert_windows_to_posix()
                    print_if('windows->posix, elapsed: '
                             f'{time.process_time() - start}')

                if m3u_from_str and m3u_to_str:
                    playlist_manager.convert_from_str_to_str(
                        from_str=m3u_from_str, to_str=m3u_to_str)
                    print_if(f'{m3u_from_str}->{m3u_to_str}, elapsed: '
                             f'{time.process_time() - start}')

                playlist_manager.write()
                print_if('Finished writing, elapsed: '
                         f'{time.process_time() - start}')
            except KeyboardInterrupt:
                print('Done...')
            except Exception:
                print('Exception while processing playlists...')
                traceback.print_exc()

    def convert_flacs(self):
        flac_dir = self.args.flac_dir
        if not flac_dir:
            return

        flac_overwrite_output = self.args.flac_overwrite_output
        flac_delete_original = self.args.flac_delete_original
        flac_threads = self.args.flac_threads

        if not FFMPEG_AVAILABLE and not XLD_AVAILABLE:
            print('Install ffmpeg or xld to use --flac_dir.')
            return

        converter = FlacToAlacConverter(
            input_dir=flac_dir,
            overwrite_output=flac_overwrite_output,
            delete_original=flac_delete_original,
            num_threads=int(flac_threads))

        try:
            converter.read()
            converter.write()

            if self.args.flac_change_genres:
                genre_changer = GenreChanger(self.args.flac_dir)
                genre_changer.read()
                genre_changer.write()

        except KeyboardInterrupt:
            if converter:
                converter.thread_kill_event.set()

            if genre_changer:
                genre_changer.thread_kill_event.set()

            print('Done...')

    def watch(self):
        self.observers: List[Observer] = []

        if self.args.m3u_watch:
            self.playlist_observer = Observer()
            self.playlist_observer.schedule(
                WatchHandler(fn=self.convert_playlists,
                             ob_name='Playlist Observer',
                             delay=self.args.watch_playlist_delay),
                true_path(self.args.m3u_input_dir),
                recursive=False)
            print_if('Will start observer with name: Playlist Observer...')
            self.observers.append(self.playlist_observer)

        if self.args.flac_watch:
            self.converter_observer = Observer()
            self.converter_observer.schedule(
                WatchHandler(fn=self.convert_flacs,
                             ob_name='FLAC Observer',
                             delay=self.args.watch_convert_delay),
                true_path(self.args.flac_dir),
                recursive=False)
            print_if('Will start observer with name: FLAC Observer...')
            self.observers.append(self.converter_observer)

        if len(self.observers) == 0:
            print_if('Not watching any directories, so finishing!')
            return

        for observer in self.observers:
            observer.start()

        try:
            while True:
                now = datetime.now()
                current_time = now.strftime('%H:%M:%S')
                print_if(f'Time: {current_time}.. Observing changes...')
                time.sleep(self.args.watch_sleep_time)
        except KeyboardInterrupt:
            print('User triggered abort.')
        except Exception:
            print('Exception while observing...')
            traceback.print_exc()
        finally:
            for observer in self.observers:
                observer.stop()
                observer.join()


def main():
    global DRY, FFMPEG_AVAILABLE, METAFLAC_AVAILABLE, MP4TAGS_AVAILABLE, \
        VERBOSE, XLD_AVAILABLE
    args = parser.parse_args()
    VERBOSE = args.verbose or args.jojo
    DRY = args.dry

    XLD_AVAILABLE = which('xld')  # OSX Only
    FFMPEG_AVAILABLE = which('ffmpeg')
    MP4TAGS_AVAILABLE = which('mp4tags')
    METAFLAC_AVAILABLE = which('metaflac')

    print_separator()
    print_if(args)
    print_separator()

    if args.change_genres:
        g = GenreChanger(input_dir=args.flac_dir)
        g.read()
        g.write()
        return

    if args.clean_up:
        print(f'Cleaning up {args.clean_up}')
        delete_some_trash(args.clean_up)
        return

    if args.jojo:
        music_manager = JojoMusicManager(args)
        music_manager.run()
    else:
        music_manager = MusicManager(args)
        music_manager.run()


if __name__ == '__main__':
    main()
