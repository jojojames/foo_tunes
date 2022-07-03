#!/usr/bin/python3

import argparse, glob, logging, os, platform, queue, re, subprocess, threading, time

from datetime import datetime
from functools import partial
from pathlib import Path, PurePosixPath, PureWindowsPath
from shutil import which, move
from typing import List, Optional, Text
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


parser = argparse.ArgumentParser(description='Foobar2000 -> iTunes utilities')

### Playlist / .m3u8 Management

parser.add_argument('-i', '--input_dir')
parser.add_argument('-o', '--output_dir', default=None)
parser.add_argument('--flac_ext_to_alac', default=False, action="store_true",
                    help='Change .flac extension to .m4a in playlists.')

parser.add_argument('--windows_to_posix', default=False, action="store_true",
                    help='Convert music paths in playlist to posix format.')

parser.add_argument('--from_str', help='String in playlist line to replace.')
parser.add_argument('--to_str', help='String in playlist line to replace to.')

### FLAC Conversion

parser.add_argument('--flac_dir',
                    help='If set, convert .flac files in this directory to .m4a.')
parser.add_argument('--flac_overwrite_output', default=False, action="store_true",
                    help='If set, always write/overwrite output files'
                    ' when converting.')
parser.add_argument('--flac_delete_original', default=False, action="store_true",
                    help='If set, delete .flac version after converting to alac.')
parser.add_argument('--flac_convert_threads', default='4',
                    help='Number of threads to use when converting.')

### Utility

parser.add_argument('--clean_up',
                    help='If set, clean up this directory of extraneous files.'
                    'This is of the form --clean_up=/some/directory')

parser.add_argument('--dry', default=False, action="store_true",
                    help="If set, don't write any new changes.")

parser.add_argument('--jojo', default=False, action="store_true",
                    help='If set, manage music.')

parser.add_argument('-v', '--verbose', default=False, action="store_true",
                    help='Verbose logging.')


def true_path(path: str) -> str:
    # https://stackoverflow.com/questions/37863476/why-would-one-use-both-os-path-abspath-and-os-path-realpath
    if path is None:
        return None
    return os.path.realpath(os.path.expanduser(path))

def flac_extension_to_alac(song: str) -> str:
    return song.replace(".flac", ".m4a").replace(".Flac", ".m4a")

def windows_path_to_posix(song: str) -> str:
    return str(PureWindowsPath(song).as_posix())

def get_write_path(output_dir: str, file: str) -> Path:
    base_name = os.path.basename(file)
    if output_dir:
        playlist_path = os.path.normpath(os.path.join(output_dir, base_name))
    else:
        playlist_path = os.path.normpath(os.path.join(os.path.dirname(file),
                                                      base_name))
    return Path(playlist_path)

def from_str_to_str(song: str, from_str: str, to_str: str) -> str:
    return song.replace(from_str, to_str)

def alac_path_from_flac_path(flac_path: str):
    directory, file_name = os.path.split(flac_path)
    base_name, extension = os.path.splitext(file_name)
    alac_path = os.path.join(directory, base_name + '.m4a')
    return alac_path

def walk_files(directory: str) -> List[str]:
    # https://stackoverflow.com/questions/19309667/recursive-os-listdir
    return [os.path.join(dp, f)
                 for dp, dn, fn in os.walk(os.path.expanduser(directory))
                 for f in fn]

def delete_some_trash(directory: str):
    """Delete extraneous trash files that may corrupt entire process."""
    files = walk_files(directory)

    # E.g.
    # ._file.flac
    # /bebe/sync/music/._file.flac
    resilio_trash_pattern = re.compile(r'(\._|^\._)')
    for f in files:
        if re.search(resilio_trash_pattern, f):
            if VERBOSE:
                print(f'Deleting trash {f}...')

            os.remove(f)

def print_separator():
    print('---------------------------------------------------------------')

class Playlist:

    def __init__(self, file: str):
        self.file = file
        self.songs = None

    def read(self):
        if self.songs:
            return
        self.songs = []
        if VERBOSE:
            print("Reading file:", self.file)
        with open(self.file, 'r') as f:
            for line in f.readlines():
                if line.strip():
                    self.songs.append(line.strip())

    def write(self, output_dir=None):
        if not self.songs:
            self.read()

        playlist_path = get_write_path(output_dir=output_dir, file=self.file)
        playlist_path.parent.mkdir(exist_ok=True, parents=True)

        if not DRY:
            with open(playlist_path, 'w', encoding='utf8') as f:
                for each in self.songs:
                    f.write(each + "\n")

        if VERBOSE or DRY:
            print('Wrote: ', playlist_path)


class PlaylistManager:
    def __init__(self, input_dir: str, output_dir: str):
        self.input_dir = true_path(input_dir)
        self.output_dir = true_path(output_dir)
        self.playlists: List[Playlist] = []

    def read(self):
        playlist_glob = os.path.join(self.input_dir, '*.m3u8')
        if VERBOSE:
            print("Globbing for: ", playlist_glob)

        playlist_files = glob.glob(playlist_glob)
        for playlist_file in playlist_files:
            playlist: Playlist = Playlist(playlist_file)
            playlist.read()
            self.playlists.append(playlist)

        if VERBOSE:
            print("Playlist Files: ", playlist_files)

    def write(self):
        for playlist in self.playlists:
            playlist.write(self.output_dir)

    def convert_extension_flac_to_alac(self):
        for playlist in self.playlists:
            playlist.songs = list(map(flac_extension_to_alac, playlist.songs))

    def convert_windows_to_posix(self):
        for playlist in self.playlists:
            playlist.songs = list(map(windows_path_to_posix, playlist.songs))

    def convert_from_str_to_str(self, from_str: str, to_str: str):
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

        sync_pattern = re.compile("\!\.sync$")
        for file in files:
            if VERBOSE:
                print(f'Looking for sync pattern in {file}...')
            if re.search(sync_pattern, file):
                if VERBOSE:
                    print(f'Found sync pattern {file}')
                return True

        return False

class MusicManager:
    def __init__(self):
        self.resilio = Resilio(sync_dir=self.get_sync_directory())

        self.playlist_manager = PlaylistManager(
            input_dir=self.get_windows_m3u_directory(),
            output_dir=self.get_alac_m3u_directory())

        self.converter = Converter(input_dir=self.get_flac_directory(),
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
        # Modify Foobar2000 m3u playlists with .flac entries to .alac.
        self.playlist_manager.read()
        self.playlist_manager.convert_extension_flac_to_alac()
        self.playlist_manager.write()

        # Write the OSX version deriving from the current list of playlists.
        self.playlist_manager.output_dir = self.get_osx_m3u_directory()
        self.playlist_manager.convert_windows_to_posix()
        self.playlist_manager.convert_from_str_to_str(
            from_str=r'X:/music', to_str=r'/Users/james/Music')
        self.playlist_manager.write()

        # Write the FreeBSD version deriving from the current list of playlists.
        self.playlist_manager.output_dir = self.get_bsd_m3u_directory()
        self.playlist_manager.convert_from_str_to_str(
            from_str=r'/Users/james/Music', to_str=r'/bebe/music')
        self.playlist_manager.write()

    def convert_and_move_flacs(self):
        flac_dir = self.get_flac_directory()
        if not os.path.exists(flac_dir):
            print(f'{flac_dir} does not exist. Skipping convert and move...')
            return

        # Get list of directories to move that aren't hidden.
        music_dirs = [f for f in os.listdir(flac_dir) if not f.startswith('.')]
        if len(music_dirs) == 0:
            print('No music directories to convert or move. Skipping.')
            return

        if self.resilio.syncing():
            print('Resilio syncing... Skipping flac conversion...')
            return

        # Attempt to convert FLACs to ALACs.
        print('Attempting flac conversion...')
        try:
            self.converter.read()
            self.converter.convert_flacs_to_alac()
            print('Finished converting...')
        except KeyboardInterrupt:
            if self.converter:
                self.converter.thread_kill_event.set()

            print("Done...")

        if self.resilio.syncing():
            print('Resilio syncing... Skipping music move...')
            return

        # Move music to Music directory.
        move_to = os.path.join(self.get_music_directory(), '_TO_PROCESS')
        if not os.path.exists(move_to):
            os.makedirs(move_to)

        ds_store_pattern = re.compile('\.DS_Store')
        for music_dir in music_dirs:
            if re.search(ds_store_pattern, music_dir):
                continue
            from_dir = os.path.join(flac_dir, music_dir)
            to_dir = os.path.join(move_to, music_dir)
            move(from_dir, to_dir)
            print(f'Moved {from_dir} to {to_dir}...')

    def setup_file_watchers(self):
        MusicManager.music_manager = self
        self.playlist_observer = Observer()
        self.playlist_observer.schedule(PlaylistWatchHandler(),
                                        self.get_windows_m3u_directory(),
                                        recursive=False)

        self.converter_observer = Observer()
        self.converter_observer.schedule(ConverterWatchHandler(),
                                         self.get_flac_directory(),
                                         recursive=False)

        self.playlist_observer.start()
        self.converter_observer.start()

        try:
            while True:
                now = datetime.now()
                current_time = now.strftime("%H:%M:%S")
                if VERBOSE:
                    print(f'Time: {current_time}.. Observing changes...')
                    time.sleep(60)
        except KeyboardInterrupt:
            print('User triggered abort.')
        except:
            print('Exception while looping...')
        finally:
            self.playlist_observer.stop()
            self.playlist_observer.join()
            self.converter_observer.stop()
            self.converter_observer.join()

    def run(self):
        self.convert_playlists()
        self.convert_and_move_flacs()
        self.setup_file_watchers()


class PlaylistWatchHandler(FileSystemEventHandler):
    """File System Watch Handler for playlist changes."""

    timer: threading.Timer = None

    @staticmethod
    def on_any_event(event):
        if VERBOSE:
            print(f'PlaylistWatchHandler: on_any_event: {event}!!')
        if event.event_type == 'created':
            if VERBOSE:
                print('PlaylistWatchHandler: Scheduling timer to convert playlists...')

            delay = 120 # Two minutes
            if PlaylistWatchHandler.timer:
                if VERBOSE:
                    print('Canceling current timer and creating a new one...')
                    PlaylistWatchHandler.timer.cancel()
                    PlaylistWatchHandler.timer = threading.Timer(
                        delay, MusicManager.music_manager.convert_playlists)
            else:
                if VERBOSE:
                    print('Creating a new timer...')
                    PlaylistWatchHandler.timer = threading.Timer(
                        delay, MusicManager.music_manager.convert_playlists)
                    print(f'Timer scheduled to start in {delay} seconds...')
                    PlaylistWatchHandler.timer.start()


class ConverterWatchHandler(FileSystemEventHandler):
    """File System Watch Handler for flac->alac changes."""

    timer: threading.Timer = None

    @staticmethod
    def on_any_event(event):
        if VERBOSE:
            print(f'ConverterWatchHandler: on_any_event: {event}!!')
        if event.event_type == 'created':
            if VERBOSE:
                print('ConverterWatchHandler: Scheduling timer to convert flacs...')

            delay = 120 # Two minutes
            if ConverterWatchHandler.timer:
                if VERBOSE:
                    print('Canceling current timer and creating a new one...')
                    ConverterWatchHandler.timer.cancel()
                    ConverterWatchHandler.timer = threading.Timer(
                        delay, MusicManager.music_manager.convert_and_move_flacs)
            else:
                if VERBOSE:
                    print('Creating a new timer...')
                    ConverterWatchHandler.timer = threading.Timer(
                        delay, MusicManager.music_manager.convert_and_move_flacs)
                    print(f'Timer scheduled to start in {delay} seconds...')
                    ConverterWatchHandler.timer.start()


class Converter:
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
        if VERBOSE:
            print('Finding files recursive for: ', self.input_dir)

        # Clean up trash first...
        delete_some_trash(self.input_dir)

        files = walk_files(self.input_dir)

        flac_pattern = re.compile("\.flac$")
        Flac_pattern = re.compile("\.Flac$")
        flac_files = []
        for f in files:
            if re.search(flac_pattern, f) or re.search(Flac_pattern, f):
                flac_files.append(f)

        if VERBOSE:
            print_separator()
            print(f'# of Flac files to convert: {len(flac_files)}')
            print(f'Flac files to convert: {flac_files}')
            print_separator()

        self.flacs = flac_files

    def convert_worker(self):
        while not self.thread_kill_event.is_set():
            try:
                flac_path, alac_path = self.queue.get_nowait()
            except:
                # Loop exits here when all threads exhaust self.queue.
                print(f'Exiting worker thread...')
                break

            print_separator()
            if os.path.exists(alac_path):
                if self.overwrite_output:
                    if VERBOSE:
                        print(f'{alac_path} exists... deleting first...')

                    os.remove(alac_path)
                else:
                    if VERBOSE:
                        print(f'{alac_path} already exists... skipping...')
                    continue

            print("Converting file {} of {}".format(
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
                     '-i', flac_path, # input file
                     '-acodec', 'alac', # 'force audio codec' to alac
                     '-vcodec', 'copy', # 'force video codec' to copy stream
                     alac_path], # 'output file'
                    # https://stackoverflow.com/questions/41171791/how-to-suppress-or-capture-the-output-of-subprocess-run
                    capture_output=True, text=True)

            if VERBOSE:
                prefix = 'xld' if XLD_AVAILABLE else 'ffmpeg'
                if process.stdout.strip():
                    print(f'{prefix}: standard out: {process.stdout}')
                if process.stderr.strip():
                    print(f'{prefix}: {process.stderr}')

                print_separator()

            # Should we try deleting even if we potentially skip converting?
            if self.delete_original:
                if VERBOSE:
                    print(f'Deleting {flac_path}...')

                os.remove(flac_path)

    def convert_flacs_to_alac(self):
        if len(self.flacs) == 0:
            if VERBOSE:
                print('No flacs to convert... skipping conversion...')
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


def main():

    global DRY, FFMPEG_AVAILABLE, VERBOSE, XLD_AVAILABLE
    args = parser.parse_args()
    input_dir = args.input_dir
    output_dir = args.output_dir
    flac_ext_to_alac = args.flac_ext_to_alac
    windows_to_posix = args.windows_to_posix
    from_str = args.from_str
    to_str = args.to_str
    flac_dir = args.flac_dir
    flac_overwrite_output = args.flac_overwrite_output
    flac_delete_original = args.flac_delete_original
    flac_convert_threads = args.flac_convert_threads
    jojo = args.jojo
    clean_up = args.clean_up
    VERBOSE = args.verbose or jojo
    DRY = args.dry

    XLD_AVAILABLE = which('xld') # OSX Only
    FFMPEG_AVAILABLE = which('ffmpeg')

    if jojo:
        music_manager = MusicManager()
        music_manager.run()
        return

    if VERBOSE:
        print_separator()
        print('--input_dir:', input_dir)
        print('--output_dir:', output_dir)
        print('--flac_ext_to_alac:', flac_ext_to_alac)
        print('--windows_to_posix:', windows_to_posix)
        print('--from_str:', from_str)
        print('--to_str:', to_str)
        print('--flac_dir:', flac_dir)
        print('--dry:', DRY)
        print('--flac_overwrite_output', flac_overwrite_output)
        print('--flac_delete_original', flac_delete_original)
        print('--flac_convert_threads', flac_convert_threads)
        print('--clean_up', clean_up)
        print('--jojo', jojo)
        print_separator()

    if clean_up:
        print(f'Cleaning up {clean_up}')
        delete_some_trash(clean_up)

    if not flac_ext_to_alac and not windows_to_posix and not flac_dir:
        print('Need to specify action... e.g. --flac_ext_to_alac')
        return

    try:
        if flac_ext_to_alac or windows_to_posix or (from_str and to_str):
            if not input_dir:
                print('Specify --input_dir...')
                return
            playlist_manager = PlaylistManager(input_dir=input_dir,
                                               output_dir=output_dir)
            playlist_manager.read()
            if flac_ext_to_alac:
                playlist_manager.convert_extension_flac_to_alac()
            if windows_to_posix:
                playlist_manager.convert_windows_to_posix()
            if from_str and to_str:
                playlist_manager.convert_from_str_to_str(from_str=from_str,
                                                         to_str=to_str)
                playlist_manager.write()

        if flac_dir:
            if not FFMPEG_AVAILABLE and not XLD_AVAILABLE:
                print('Install ffmpeg or xld to use --flac_dir.')
                return

            converter = Converter(input_dir=flac_dir,
                                  overwrite_output=flac_overwrite_output,
                                  delete_original=flac_delete_original,
                                  num_threads=int(flac_convert_threads))
            converter.read()
            converter.convert_flacs_to_alac()

    except KeyboardInterrupt:
        if converter:
            converter.thread_kill_event.set()
            print("Done...")

if __name__ == '__main__':
    main()
