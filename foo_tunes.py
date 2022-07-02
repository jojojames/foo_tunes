#!/usr/bin/python3

import glob, os, logging, argparse, re, queue, threading, subprocess, time

from functools import partial
from pathlib import Path, PurePosixPath, PureWindowsPath
from shutil import which
from typing import List, Optional, Text


parser = argparse.ArgumentParser(description='Foobar2000 -> iTunes utilities')

parser.add_argument('-i', '--input_dir')
parser.add_argument('-o', '--output_dir', default=None)
parser.add_argument('-v', '--verbose', default=False, action="store_true",
                    help='Verbose logging.')

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

parser.add_argument('--dry', default=False, action="store_true",
                    help="If set, don't write any new changes.")

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


class FooTunes:
    def __init__(self, input_dir: str, output_dir: str):
        self.input_dir = input_dir
        self.output_dir = output_dir
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


class FFMpegWrapper:
    def __init__(self, input_dir: str, overwrite_output: bool):
        self.input_dir = input_dir
        self.flacs = []
        self.queue = queue.Queue()
        self.threads = []
        self.thread_kill_event = threading.Event()
        self.overwrite_output = overwrite_output

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
        possible_cover_image_names = ['cover.jpg']

        for cover_image_name in possible_cover_image_names:
            path: Text = os.path.join(os.path.dirname(path), cover_image_name)
            if os.path.exists(path):
                return path

        return None

    def convert_worker(self):
        while not self.thread_kill_event.is_set():
            try:
                flac_path, alac_path = self.queue.get_nowait()
            except:
                break

            print_separator()
            print("Converting file {} of {}".format(
                self.total_queue_size - self.queue.qsize(),
                self.total_queue_size), flush=True)
            print('From:', flac_path)
            print('To:', alac_path)
            print_separator()

            if os.path.exists(alac_path):
                if self.overwrite_output:
                    print(f'{alac_path} already exists... deleting...')
                    os.remove(alac_path)
                else:
                    print(f'{alac_path} already exists... skipping...')
                    continue

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
                print_separator()
                print("convert stdout: ", process.stdout)
                print("convert stderr: ", process.stderr)
                print_separator()

            if not MP4ART_AVAILABLE:
                return
            cover_image: Optional[Text] = self.get_cover_image(flac_path)
            if not cover_image:
                if VERBOSE:
                    print('Cover image not found for:', flac_path)
                return
            art_process = subprocess.run(
                # https://stackoverflow.com/questions/17798709/ffmpeg-how-to-embed-cover-art-image-to-m4a
                ['mp4art', '--add', cover_image, alac_path],
                capture_output=True, text=True)
            if VERBOSE:
                print_separator()
                print("art stdout: ", art_process.stdout)
                print("art stderr: ", art_process.stderr)
                print_separator()


    def convert_flacs_to_alac(self):
        for flac_path in self.flacs:
            alac_path = alac_path_from_flac_path(flac_path=flac_path)
            self.queue.put((flac_path, alac_path))
            self.total_queue_size = self.queue.qsize()
        for i in range(4):
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
    input_dir = true_path(args.input_dir)
    output_dir = true_path(args.output_dir)
    flac_ext_to_alac = args.flac_ext_to_alac
    windows_to_posix = args.windows_to_posix
    from_str = args.from_str
    to_str = args.to_str
    flac_dir = true_path(args.flac_dir)
    flac_overwrite_output = args.flac_overwrite_output
    VERBOSE = args.verbose
    DRY = args.dry

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
        print_separator()

    if not flac_ext_to_alac and not windows_to_posix and not flac_dir:
        print('Need to specify action... e.g. --flac_ext_to_alac')
        return

    try:
        if flac_ext_to_alac or windows_to_posix or (from_str and to_str):
            if not input_dir:
                print('Specify --input_dir...')
                return
            foo_tunes = FooTunes(input_dir=input_dir, output_dir=output_dir)
            foo_tunes.read()
            if flac_ext_to_alac:
                foo_tunes.convert_extension_flac_to_alac()
            if windows_to_posix:
                foo_tunes.convert_windows_to_posix()
            if from_str and to_str:
                foo_tunes.convert_from_str_to_str(from_str=from_str,
                                                  to_str=to_str)
                foo_tunes.write()

        if flac_dir:
            # https://stackoverflow.com/questions/11210104/check-if-a-program-exists-from-a-python-script
            if which('ffmpeg') is None:
                print('Install ffmpeg to use --flac_dir.')
                return

            if which('mp4art') is None:
                # OSX: brew install mp4v2
                print('Installing mp4v2 [e.g. with $ brew install mp4v2] allows adding cover art')
                MP4ART_AVAILABLE = False
            else:
                print('mp4v2 available, will attempt to add cover art.')
                MP4ART_AVAILABLE = True

            ffmpeg_wrapper = FFMpegWrapper(input_dir=flac_dir,
                                           overwrite_output=flac_overwrite_output)
            ffmpeg_wrapper.read()
            ffmpeg_wrapper.convert_flacs_to_alac()

    except KeyboardInterrupt:
        if ffmpeg_wrapper:
            ffmpeg_wrapper.thread_kill_event.set()
            print("Done...")

if __name__ == '__main__':
    main()
