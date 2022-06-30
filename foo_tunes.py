#!/usr/bin/python3

import glob, os, logging, argparse

from pathlib import Path
from typing import List


parser = argparse.ArgumentParser(description='Foobar2000 -> iTunes utilities')

parser.add_argument('-i', '--input_dir')
parser.add_argument('-o', '--output_dir', default=None)
parser.add_argument('-v', '--verbose', default=False, action="store_true",
                    help="Verbose logging.")

parser.add_argument('--flac_ext_to_alac', default=True, action="store_true",
                    help="Change .flac extension to .m4a in playlists.")

parser.add_argument('--dry', default=False, action="store_true",
                    help="If set, don't write any new changes.")

def flac_extension_to_alac(song: str) -> str:
    return song.replace(".flac", ".m4a").replace(".Flac", ".m4a")

def get_write_path(output_dir: str, file: str) -> Path:
    base_name = os.path.basename(file)
    if output_dir:
        playlist_path = os.path.normpath(os.path.join(output_dir, base_name))
    else:
        playlist_path = os.path.normpath(os.path.join(os.path.dirname(file),
                                                      base_name))
    return Path(playlist_path)

class Playlist:

    def __init__(self, file):
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

        if VERBOSE:
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
            songs = list(map(flac_extension_to_alac, playlist.songs))
            playlist.songs = songs

def main():
    global DRY, VERBOSE
    args = parser.parse_args()
    input_dir = os.path.abspath(args.input_dir)
    output_dir = os.path.abspath(args.output_dir) if args.output_dir else None
    flac_ext_to_alac = args.flac_ext_to_alac
    VERBOSE = args.verbose
    DRY = args.dry

    if VERBOSE:
        print('Input: ', input_dir)
        print('Output: ', output_dir)

    if not flac_ext_to_alac:
        print('Need to specify action... e.g. --flac_ext_to_alac')
        return

    try:
        foo_tunes = FooTunes(input_dir=input_dir, output_dir=output_dir)
        foo_tunes.read()
        if flac_ext_to_alac:
            foo_tunes.convert_extension_flac_to_alac()
        foo_tunes.write()
    except KeyboardInterrupt:
        print("Done...")

if __name__ == '__main__':
    main()
