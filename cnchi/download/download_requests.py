#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# download_requests.py
#
# Copyright © 2013-2015 Antergos
#
# This file is part of Cnchi.
#
# Cnchi is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# Cnchi is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# The following additional terms are in effect as per Section 7 of the license:
#
# The preservation of all legal notices and author attributions in
# the material or in the Appropriate Legal Notices displayed
# by works containing it is required.
#
# You should have received a copy of the GNU General Public License
# along with Cnchi; If not, see <http://www.gnu.org/licenses/>.


""" Module to download packages using requests library """

import os
import logging
import queue
import shutil
import requests
import time
import hashlib
import socket
import io
import threading


def get_md5(file_name):
    """ Gets md5 hash from a file """
    md5_hash = hashlib.md5()
    with open(file_name, "rb") as myfile:
        for line in myfile:
            md5_hash.update(line)
    return md5_hash.hexdigest()


class CopyToCache(threading.Thread):
    ''' Class thread to copy a xz file to the user's
        provided cache directory '''
    def __init__(self, origin, xz_cache_dirs):
        threading.Thread.__init__(self)
        self.origin = origin
        self.xz_cache_dirs = xz_cache_dirs

    def run(self):
        basename = os.path.basename(self.origin)
        for xz_cache_dir in self.xz_cache_dirs:
            dst = os.path.join(xz_cache_dir, basename)
            # Try to copy the file, do not worry if it's not possible
            try:
                shutil.copy(self.origin, dst)
            except (FileNotFoundError, FileExistsError, OSError):
                pass


class Download(object):
    """ Class to download packages using requests
        This class tries to previously download all necessary packages for
        Antergos installation using requests """

    def __init__(self, pacman_cache_dir, xz_cache_dirs, callback_queue):
        """ Initialize Download class. Gets default configuration """
        self.pacman_cache_dir = pacman_cache_dir
        self.xz_cache_dirs = xz_cache_dirs
        self.callback_queue = callback_queue

        # Check that pacman cache directory exists
        os.makedirs(self.pacman_cache_dir, mode=0o755, exist_ok=True)

        # Stores last issued event (to prevent repeating events)
        self.last_event = {}

        self.copy_to_cache_threads = []

    def is_hash_ok(self, element, dst_path):
        """ Checks file md5 hash """
        # Check the file's md5 hash
        # element['hash'] is not always available
        # that is why we use get() with default of False
        md5 = get_md5(dst_path)
        md5hash = element.get('hash', False)
        if md5hash and md5hash != md5:
            logging.debug(
                "MD5 hash of file %s does not match what's in the repository database!",
                element['filename'])
            is_ok = False
        elif md5hash == md5 or not md5hash:
            # Hash ok or can't be checked (is False or an empty string)
            self.queue_event(
                'cache_pkgs_md5_check_failed',
                element['identity'])
            logging.debug(
                    'Checksum unavailable for package: %s',
                    element['identity'])
            is_ok = True
        return is_ok

    def start(self, downloads):
        """ Downloads using requests """
        downloaded = 0
        total_downloads = len(downloads)
        download_error = False
        needs_to_download = False

        self.queue_event('downloads_progress_bar', 'show')
        self.queue_event('downloads_percent', '0')

        self.copy_to_cache_threads = []

        logging.debug(
            "Downloading packages to pacman cache dir '%s'",
            self.pacman_cache_dir)

        while len(downloads) > 0:
            identity, element = downloads.popitem()

            self.queue_event('percent', '0')

            txt = _("Downloading {0} {1} ({2}/{3})...").format(
                element['identity'],
                element['version'],
                downloaded + 1,
                total_downloads)
            self.queue_event('info', txt)

            try:
                total_length = int(element['size'])
            except TypeError:
                # No problem, we will get the total length from the requests GET
                pass

            dst_path = os.path.join(self.pacman_cache_dir, element['filename'])

            if os.path.exists(dst_path):
                # File already exists in destination pacman's cache
                # (previous install?). We check the file md5 hash.
                if not self.is_hash_ok(element, dst_path):
                    # Wrong hash. Force to download it
                    needs_to_download = True
                else:
                    needs_to_download = False
                    logging.debug(
                        "File %s already exists, Cnchi will not overwrite it",
                        element['filename'])
            else:
                needs_to_download = True
                # Check all cache directories
                for xz_cache_dir in self.xz_cache_dirs:
                    dst_xz_cache_path = os.path.join(
                        xz_cache_dir,
                        element['filename'])

                    if (os.path.exists(dst_xz_cache_path) and
                            self.is_hash_ok(element, dst_xz_cache_path)):
                        # We're lucky, the package is already downloaded
                        # in the cache the user has given us
                        # and its md5 checks out (if there is a md5)
                        logging.debug(
                            "%s found in suplied xz packages' cache. Copying...",
                            element['filename'])
                        try:
                            shutil.copy(dst_xz_cache_path, dst_path)
                            needs_to_download = False
                            # Get out of the for loop, as we managed
                            # to find the package in this cache directory
                            break
                        except OSError as os_error:
                            logging.debug(
                                "Error copying %s to %s : %s",
                                dst_xz_cache_path,
                                dst_path,
                                os_error)

            if needs_to_download and not self.download_package(element, dst_path):
                # None of the mirror urls works.
                # Stop right here, so the user does not have to wait
                # to download the other packages.
                msg = "Can't download {0}, even after trying all available mirrors"
                msg = msg.format(element['filename'])
                logging.error(msg)
                return False
            else:
                downloaded += 1

            self.queue_event('progress_bar_show_text', '')

            downloads_percent = round(float(downloaded / total_downloads), 2)
            self.queue_event('downloads_percent', str(downloads_percent))

        # Wait until all xz packages are also copied to provided cache (if any)
        for cache_thread in self.copy_to_cache_threads:
            cache_thread.join()

        self.queue_event('downloads_progress_bar', 'hide')
        return True

    def download_package(self, element, dst_path):
        """ Package wasn't previously downloaded or its md5 was wrong
            We'll have to download it
            Let's download our file using its url """

        download_error = True

        for url in element['urls']:
            # Let's catch empty values as well as None just to be safe
            if not url:
                # Something bad has happened, let's try another mirror
                download_error = True
                logging.debug(
                    "Package %s v%s has an empty url for this mirror",
                    element['identity'],
                    element['version'])
                continue
            percent = 0
            completed_length = 0
            start = time.perf_counter()
            try:
                # By default, get waits five minutes before
                # issuing a timeout, which is too much.
                req = requests.get(url, stream=True, timeout=30)
                if req.status_code == requests.codes.ok:
                    # Get total file length
                    try:
                        total_length = int(req.headers.get('content-length'))
                    except TypeError:
                        total_length = 0
                        logging.debug(
                            "Metalink for package %s has no size info",
                            element['identity'])

                    with open(dst_path, 'wb') as xz_file:
                        for data in req.iter_content(io.DEFAULT_BUFFER_SIZE):
                            if not data:
                                break
                            xz_file.write(data)
                            completed_length += len(data)
                            old_percent = percent
                            if total_length > 0:
                                percent = float(completed_length / total_length)
                                percent = round(percent, 2)
                            else:
                                percent += 0.1
                            if old_percent != percent:
                                self.queue_event('percent', percent)
                            bps = completed_length // (time.perf_counter() - start)
                            msg = self.format_progress_message(percent, bps)
                            self.queue_event('progress_bar_show_text', msg)

                    # Check hash of downloaded package
                    if not self.is_hash_ok(element, dst_path):
                        # Wrong md5! Force to download it again
                        download_error = True
                        logging.debug(
                            "MD5 hash of file %s (%s) do not match! Cnchi will try another mirror.",
                            element['filename'],
                            url)
                        continue

                    # If we've reached here let's assume it's ok
                    download_error = False

                    # Copy downloaded xz file to the cache the user has provided, too.
                    copy_to_cache_thread = CopyToCache(dst_path, self.xz_cache_dirs)
                    self.copy_to_cache_threads += [copy_to_cache_thread]
                    copy_to_cache_thread.start()

                    # Get out of the for loop, as we managed
                    # to download the package
                    break
                else:
                    # requests failed to obtain the file. Wrong url?
                    download_error = True
                    msg = "Can't download {0}, Cnchi will try another mirror."
                    msg = msg.format(url)
                    logging.debug(msg)
                    continue
            except (socket.timeout,
                    requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError) as connection_error:
                download_error = True
                msg = "Can't download {0} ({1}), Cnchi will try another mirror in a minute."
                msg = msg.format(url, connection_error)
                logging.debug(msg)
                # delays for 60 seconds
                time.sleep(60)
                continue
        return download_error

    def format_progress_message(self, percent, bps):
        """ Formats speed message information """
        if bps >= (1024 * 1024):
            Mbps = bps / (1024 * 1024)
            msg = "{0}%   {1:.2f} Mbps".format(int(percent * 100), Mbps)
        elif bps >= 1024:
            Kbps = bps / 1024
            msg = "{0}%   {1:.2f} Kbps".format(int(percent * 100), Kbps)
        else:
            msg = "{0}%   {1:.2f} bps".format(int(percent * 100), bps)
        return msg

    def queue_event(self, event_type, event_text=None):
        """ Adds an event to Cnchi event queue """

        if self.callback_queue is None:
            if event_type != "percent":
                logging.debug("{0}: {1}".format(event_type, event_text))
            return

        if event_type in self.last_event:
            if self.last_event[event_type] == event_text:
                # do not repeat same event
                return

        self.last_event[event_type] = event_text

        try:
            # Add the event
            self.callback_queue.put_nowait((event_type, event_text))
        except queue.Full:
            pass
