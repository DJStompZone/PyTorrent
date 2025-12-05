import base64
import binascii
import math
import os
import time
from urllib.parse import parse_qs, urlparse

__author__ = 'alexisgallepe'

import hashlib
import logging
import requests
from bcoding import bencode, bdecode


class Torrent(object):
    def __init__(self):
        self.torrent_file = {}
        self.total_length: int = 0
        self.piece_length: int = 0
        self.pieces: int = 0
        self.info_hash: str = ''
        self.peer_id: str = ''
        self.announce_list = ''
        self.file_names = []
        self.number_of_pieces: int = 0

    def load_from_path(self, path):
        with open(path, 'rb') as file:
            contents = bdecode(file)

        return self._load_from_torrent_file(contents)

    def load_from_magnet(self, magnet_uri: str):
        info_hash = self._extract_info_hash(magnet_uri)
        torrent_bytes = self._download_torrent_from_info_hash(info_hash)
        contents = bdecode(torrent_bytes)

        return self._load_from_torrent_file(contents)

    def load_from_uri(self, uri: str):
        if uri.startswith("magnet:?"):
            return self.load_from_magnet(uri)

        if not os.path.isfile(uri):
            raise FileNotFoundError(f"Torrent file not found at path: {uri}")

        return self.load_from_path(uri)

    def _load_from_torrent_file(self, contents):
        self.torrent_file = contents
        self.piece_length = self.torrent_file['info']['piece length']
        self.pieces = self.torrent_file['info']['pieces']
        raw_info_hash = bencode(self.torrent_file['info'])
        self.info_hash = hashlib.sha1(raw_info_hash).digest()
        self.peer_id = self.generate_peer_id()
        self.announce_list = self.get_trakers()
        self.init_files()
        self.number_of_pieces = math.ceil(self.total_length / self.piece_length)
        logging.debug(self.announce_list)
        logging.debug(self.file_names)

        assert(self.total_length > 0)
        assert(len(self.file_names) > 0)

        return self

    def _extract_info_hash(self, magnet_uri: str) -> str:
        parsed = urlparse(magnet_uri)
        if parsed.scheme != "magnet":
            raise ValueError("Invalid magnet URI")

        query = parse_qs(parsed.query)
        xt_params = query.get("xt", [])
        for xt in xt_params:
            if xt.startswith("urn:btih:"):
                info_hash = xt.split(":")[-1]
                try:
                    bytes.fromhex(info_hash)
                    return info_hash.lower()
                except ValueError:
                    try:
                        decoded = base64.b32decode(info_hash)
                        return decoded.hex()
                    except binascii.Error:
                        continue

        raise ValueError("Unable to parse info hash from magnet URI")

    def _download_torrent_from_info_hash(self, info_hash: str) -> bytes:
        urls = [
            f"https://itorrents.org/torrent/{info_hash}.torrent",
            f"https://btcache.me/torrent/{info_hash}",
        ]

        for url in urls:
            try:
                response = requests.get(url, timeout=10)
            except requests.RequestException as exc:
                logging.debug("Failed to fetch %s: %s", url, exc)
                continue

            if response.status_code == 200 and response.content:
                return response.content

            logging.debug("Torrent not available at %s (status %s)", url, response.status_code)

        raise ConnectionError("Could not download torrent metadata from available magnet mirrors")

    def init_files(self):
        root = self.torrent_file['info']['name']

        if 'files' in self.torrent_file['info']:
            if not os.path.exists(root):
                os.mkdir(root, 0o0766 )

            for file in self.torrent_file['info']['files']:
                path_file = os.path.join(root, *file["path"])

                if not os.path.exists(os.path.dirname(path_file)):
                    os.makedirs(os.path.dirname(path_file))

                self.file_names.append({"path": path_file , "length": file["length"]})
                self.total_length += file["length"]

        else:
            self.file_names.append({"path": root , "length": self.torrent_file['info']['length']})
            self.total_length = self.torrent_file['info']['length']

    def get_trakers(self):
        if 'announce-list' in self.torrent_file:
            return self.torrent_file['announce-list']
        else:
            return [[self.torrent_file['announce']]]

    def generate_peer_id(self):
        seed = str(time.time())
        return hashlib.sha1(seed.encode('utf-8')).digest()
