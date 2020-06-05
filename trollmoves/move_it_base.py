#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2012, 2013, 2014, 2015, 2016
#
# Author(s):
#
#   Martin Raspaud <martin.raspaud@smhi.se>
#   Panu Lahtinen <panu.lahtinen@fmi.fi>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Base class for move_it_{client,server,mirror}."""

import logging
import logging.handlers
import os

import pyinotify

from trollmoves.server import EventHandler

LOGGER = logging.getLogger("move_it_base")
LOG_FORMAT = "[%(asctime)s %(levelname)-8s %(name)s] %(message)s"


class MoveItBase(object):
    """Base class for Trollmoves."""

    def __init__(self, cmd_args, chain_type):
        """Initialize the class."""
        self.cmd_args = cmd_args
        self.chain_type = chain_type
        self.running = False
        self.notifier = None
        self.watchman = None
        self.sync_publisher = None
        self._np = None
        self.chains = {}
        setup_logging(cmd_args, chain_type)
        LOGGER.info("Starting up.")
        self.setup_watchers(cmd_args)

    def reload_cfg_file(self, filename, *args, **kwargs):
        """Reload configuration file."""
        if self.chain_type == "client":
            from trollmoves.client import reload_config
            reload_config(filename, self.chains, *args, sync_publisher=self.sync_publisher,
                          **kwargs)
        else:
            # Also Mirror uses the reload_config from the Server
            from trollmoves.server import reload_config
            reload_config(filename, self.chains, *args, publisher=self.sync_publisher,
                          use_watchdog=self.cmd_args.watchdog,
                          disable_backlog=self.cmd_args.disable_backlog)

    def signal_reload_cfg_file(self, *args):
        """Handle reload signal."""
        del args
        if self.chain_type == "client":
            from trollmoves.client import reload_config
            reload_config(self.cmd_args.config_file, self.chains,
                          sync_publisher=self.sync_publisher)
        else:
            from trollmoves.server import reload_config
            reload_config(self.cmd_args.config_file, self.chains,
                          publisher=self.sync_publisher,
                          use_watchdog=self.cmd_args.watchdog,
                          disable_backlog=self.cmd_args.disable_backlog)

    def chains_stop(self, *args):
        """Stop all transfer chains."""
        del args
        if self.chain_type == "client":
            from trollmoves.client import terminate
        else:
            from trollmoves.server import terminate
        self.running = False
        self.notifier.stop()
        try:
            self._np.stop()
        except AttributeError:
            pass
        terminate(self.chains)

    def setup_watchers(self, cmd_args):
        """Set up watcher for the configuration file."""
        mask = (pyinotify.IN_CLOSE_WRITE |
                pyinotify.IN_MOVED_TO |
                pyinotify.IN_CREATE)
        self.watchman = pyinotify.WatchManager()

        event_handler = EventHandler(self.reload_cfg_file,
                                     watchManager=self.watchman,
                                     tmask=mask,
                                     cmd_filename=self.cmd_args.config_file)
        self.notifier = pyinotify.ThreadedNotifier(self.watchman, event_handler)
        self.watchman.add_watch(os.path.dirname(cmd_args.config_file), mask)


def setup_logging(cmd_args, chain_type):
    """Set up logging."""
    global LOGGER
    LOGGER = logging.getLogger('')
    if cmd_args.verbose:
        LOGGER.setLevel(logging.DEBUG)

    if cmd_args.log:
        fh_ = logging.handlers.TimedRotatingFileHandler(
            os.path.join(cmd_args.log),
            "midnight",
            backupCount=7)
    else:
        fh_ = logging.StreamHandler()

    formatter = logging.Formatter(LOG_FORMAT)
    fh_.setFormatter(formatter)

    LOGGER.addHandler(fh_)
    logger_name = "move_it_server"
    if chain_type == "client":
        logger_name = "move_it_client"
    elif chain_type == "mirror":
        logger_name = "move_it_mirror"
    LOGGER = logging.getLogger(logger_name)
    pyinotify.log.handlers = [fh_]
