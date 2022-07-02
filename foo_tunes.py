#!/usr/bin/python3

import glob, os, logging, argparse, re, queue, threading, subprocess, time, platform

from functools import partial
from pathlib import Path, PurePosixPath, PureWindowsPath
from shutil import which, move
from typing import List, Optional, Text


parser = argparse.ArgumentParser(description='Foobar2000 -> iTunes utilities')

parser.add_argument('-i', '--input_dir')
parser.add_argument('-o', '--output_dir', default=None)
parser.add_argument('--flac_ext_to_alac', default=False, action="store_true",
                    help='Change .flac extension to .m4a in playlists.')

parser.add_argument('--windows_to_posix', default=False, action="store_true",
                    help='Convert music paths in playlist to posix format.')

parser.add_argument('--from_str', help='String in playlist line to replace.')
parser.add_argument('--to_str', help='String in playlist line to replace to.')

parser.add_argument('--flac_dir',
                    help='If set, convert .flac files in this directory to .m4a.')
parser.add_argument('--flac_overwrite_output', default=False, action="store_true",
                    help='If set, always write new files with ffmpeg.')
parser.add_argument('--flac_delete_original', default=False, action="store_true",
                    help='If set, delete .flac version after converting to alac.')
parser.add_argument('--flac_convert_threads',
                    help='Number of threads to use when converting.')

parser.add_argument('--jojo', default=False, action="store_true",
                    help='If set, manage music.')

parser.add_argument('--dry', default=False, action="store_true",
                    help="If set, don't write any new changes.")
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

        self.ffmpeg = FFMpeg(input_dir=self.get_flac_directory(),
                             overwrite_output=True,
                             delete_original=False)

    def get_playlist_directory(self):
        if platform.system() == 'Windows':
            return r'X:\playlists'
        if platform.system() == 'Darwin':
            return r'/Volumes/bebe/playlists'
        if platform.system == 'FreeBSD':
            return r'/bebe/playlists'

    def get_windows_m3u_directory(self):
        return os.path.join(self.get_playlist_directory(), 'windows')

    def get_alac_m3u_directory(self):
        return os.path.join(self.get_playlist_directory(), 'alac')

    def get_osx_m3u_directory(self):
        return os.path.join(self.get_playlist_directory(), 'osx')

    def get_sync_directory(self):
        if platform.system() == 'Windows':
            return r'X:\sync'
        if platform.system() == 'Darwin':
            return r'/Volumes/bebe/sync'
        if platform.system == 'FreeBSD':
            return r'/bebe/sync'

    def get_flac_directory(self):
        if platform.system() == 'Windows':
            return r'X:\sync\flacsfor.me'
        if platform.system() == 'Darwin':
            return r'/Volumes/bebe/sync/flacsfor.me'
        if platform.system == 'FreeBSD':
            return r'/bebe/sync/flacsfor.me'

    def get_music_directory(self):
        if platform.system() == 'Windows':
            return r'X:\music'
        if platform.system() == 'Darwin':
            return r'/Volumes/bebe/music'
        if platform.system == 'FreeBSD':
            return r'/bebe/music'

    def run(self):
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

        flac_dir = self.get_flac_directory()
        if not os.path.exists(flac_dir):
            print(f'{flac_dir} does not exist. Skipping convert and move...')
            return

        music_dirs = os.listdir(flac_dir)
        if len(music_dirs) == 0:
            print('No music directories to convert or move. Skipping.')
            return

        if self.resilio.syncing():
            print('Resilio syncing... Skipping ffmpeg flac conversion...')
            return

        # Attempt to convert FLACs to ALACs.
        print('Attempting ffmpeg flac conversion...')
        try:
            self.ffmpeg.read()
            self.ffmpeg.convert_flacs_to_alac()
            print('ffmpeg finished converting...')
        except KeyboardInterrupt:
            if self.ffmpeg:
                self.ffmpeg.thread_kill_event.set()

            print("Done...")

        if self.resilio.syncing():
            print('Resilio syncing... Skipping music move...')
            return

        # Move music to Music directory.
        move_to = os.path.join(self.get_music_directory(), '_TO_PROCESS')
        if not os.path.exists(move_to):
            os.makedirs(move_to)
        for music_dir in music_dirs:
            from_dir = os.path.join(flac_dir, music_dir)
            to_dir = os.path.join(move_to, music_dir)
            move(from_dir, to_dir)
            print(f'Moved {from_dir} to {to_dir}...')


class FFMpeg:
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

        # https://stackoverflow.com/questions/19309667/recursive-os-listdir
        files = [os.path.join(dp, f)
                 for dp, dn, fn in os.walk(os.path.expanduser(self.input_dir))
                 for f in fn]

        flac_pattern = re.compile("\.flac$")
        Flac_pattern = re.compile("\.Flac$")
        flac_files = []
        for f in files:
            if re.search(flac_pattern, f) or re.search(Flac_pattern, f):
                flac_files.append(f)

        if VERBOSE:
            print_separator()
            print('Flac files to convert: ', flac_files)
            print_separator()

        self.flacs = flac_files

    def get_cover_image(self, path: str) -> Optional[Text]:
        # First look for possible cover image names.
        possible_cover_image_names = ['cover.jpg',
                                      'Cover.jpg',
                                      'FOLDER.jpg',
                                      'folder.jpg']

        directory = os.path.dirname(path)
        for cover_image_name in possible_cover_image_names:
            path: Text = os.path.join(directory, cover_image_name)
            if os.path.exists(path):
                return path

        # Give up and glob for the extension instead.
        jpg_glob = os.path.join(directory, '*.jpg')
        if VERBOSE:
            print("Globbing for: ", directory)

        jpg_files = glob.glob(jpg_glob)
        # Return first jpg we find if it exists.
        for jpg_file in jpg_files:
            return os.path.join(directory, jpg_file)

        # Give up, no cover images.
        return None

    def convert_worker(self):
        while not self.thread_kill_event.is_set():
            try:
                flac_path, alac_path = self.queue.get_nowait()
            except:
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

            # Adding cover art seems like it may not work when using -movflags.
            # Without -movflags, none of the additional metadata is migrated though.
            process = subprocess.run(
                # https://unix.stackexchange.com/questions/415477/lossless-audio-conversion-from-flac-to-alac-using-ffmpeg
                ['ffmpeg',
                 # https://superuser.com/questions/326629/how-can-i-make-ffmpeg-be-quieter-less-verbose
                 '-v', 'info' if VERBOSE else 'warning',
                 '-i', flac_path, # input file
                 '-acodec', 'alac', # 'force audio codec' to alac
                 '-vcodec', 'copy', # 'force video codec' to copy stream
                 # For preserving extra metadata flags,
                 # e.g. replaygain, ALBUM, ARTIST, COMPOSER, ITUNESADVISORY etc.
                 # https://superuser.com/questions/469650/converting-flac-to-alac-preserving-tags-in-a-script
                 # https://stackoverflow.com/questions/59725816/dealing-with-problems-in-flac-audio-files-with-ffmpeg
                 # https://superuser.com/questions/523286/how-to-make-handbrake-preserve-capture-time-creation-time/523696#comment2528176_523696
                 # https://superuser.com/questions/996223/using-ffmpeg-to-copy-metadata-from-one-file-to-another
                 '-map_metadata', '0',
                 '-movflags',
                 'use_metadata_tags',
                 alac_path], # 'output file'
                # https://stackoverflow.com/questions/41171791/how-to-suppress-or-capture-the-output-of-subprocess-run
                capture_output=True, text=True)

            if VERBOSE:
                if process.stdout.strip():
                    print(f"FFMPEG: standard out: {process.stdout}")
                if process.stderr.strip():
                    print(f'FFMPEG: {process.stderr}')

                print_separator()

            # Should we try deleting even if we potentially skip converting?
            if self.delete_original:
                if VERBOSE:
                    print(f'Deleting {flac_path}...')

                os.remove(flac_path)

            if not MP4ART_AVAILABLE:
                return

            cover_image: Optional[Text] = self.get_cover_image(flac_path)
            if not cover_image:
                if VERBOSE:
                    print('Cover image not found for:', flac_path)

                continue

            art_process = subprocess.run(
                # https://stackoverflow.com/questions/17798709/ffmpeg-how-to-embed-cover-art-image-to-m4a
                ['mp4art', '--add', cover_image, alac_path],
                capture_output=True, text=True)
            if VERBOSE:
                if art_process.stdout.strip():
                    print(f'Cover Art: {art_process.stdout}')
                if art_process.stderr.strip():
                    print(f'Cover Art Error: {art_process.stderr}')


    def convert_flacs_to_alac(self):
        for flac_path in self.flacs:
            alac_path = alac_path_from_flac_path(flac_path=flac_path)
            self.queue.put((flac_path, alac_path))
            self.total_queue_size = self.queue.qsize()
        for i in range(self.num_threads):
            thread = threading.Thread(target=self.convert_worker)
            thread.start()
            self.threads.append(thread)
        while threading.active_count() > 1:
            time.sleep(1)
        for thread in self.threads:
            thread.join()


def main():

    global DRY, VERBOSE, MP4ART_AVAILABLE
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
    VERBOSE = args.verbose or jojo
    DRY = args.dry

    # https://stackoverflow.com/questions/11210104/check-if-a-program-exists-from-a-python-script
    MP4ART_AVAILABLE = which('mp4art')
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
        print('--jojo', jojo)
        print_separator()

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
            if not FFMPEG_AVAILABLE:
                print('Install ffmpeg to use --flac_dir.')
                return

            if MP4ART_AVAILABLE:
                print('mp4v2 available, will attempt to add cover art.')
            else:
                # OSX: brew install mp4v2
                print('Installing mp4v2 [e.g. with $ brew install mp4v2] allows adding cover art')

            ffmpeg_wrapper = FFMpeg(input_dir=flac_dir,
                                    overwrite_output=flac_overwrite_output,
                                    delete_original=flac_delete_original,
                                    num_threads=int(flac_convert_threads))
            ffmpeg_wrapper.read()
            ffmpeg_wrapper.convert_flacs_to_alac()

    except KeyboardInterrupt:
        if ffmpeg_wrapper:
            ffmpeg_wrapper.thread_kill_event.set()
            print("Done...")

if __name__ == '__main__':
    main()
