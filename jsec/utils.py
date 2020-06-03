#!/usr/bin/env python3
import argparse
import configparser
import enum
import logging
import os
import re
import subprocess as sp
import sys
import time
from contextlib import contextmanager

from jsec.settings import LIB_DIR

# from collections import namedtuple
from typing import NamedTuple
from typing import Optional
from typing import List

import pymongo

from jsec.settings import LIB_DIR

log = logging.getLogger(__file__)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(levelname)s:%(asctime)s:%(name)s: %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

# FIXME use enum and allow 'debug' as value for --verbose
LOG_LEVELS = [
    logging.DEBUG,
    logging.INFO,
    logging.WARNING,
    logging.ERROR,
    logging.CRITICAL,
]


class Error(enum.Enum):
    UNSUPPORTED_PYTHON_VERSION = -1


# kudos to: https://medium.com/@ramojol/python-context-managers-and-the-with-statement-8f53d4d9f87
class MongoConnection(object):
    def __init__(
        self,
        host="localhost",
        port="27017",
        database="card-analysis",
        collation="commands",
    ):
        self.host = host
        self.port = port
        self.connection = None
        self.db_name = database
        self.collation_name = collation

    def __enter__(self, *args, **kwargs):
        conn_str = f"mongodb://{self.host}:{self.port}"
        log.debug("Starting the connection with %s", conn_str)

        self.connection = pymongo.MongoClient(conn_str)
        self.db = self.connection[self.db_name]
        self.col = self.db[self.collation_name]
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        log.debug("Closing the connection to the database")
        self.connection.close()


class Timer(object):
    # naive timer, but to get at least an idea
    def __init__(self):
        self.start = None
        self.end = None
        self.duration = None

    def __enter__(self, *args, **kwargs):
        self.start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end = time.time()
        self.duration = self.end - self.start


class CommandLineApp(object):
    """
    Template for Python command line applications.
    """

    APP_DESCRIPTION = None

    def __init__(self):
        self.verbosity = logging.ERROR
        self.args = None

        self.parser = argparse.ArgumentParser(description=self.APP_DESCRIPTION,)
        self.add_options()
        self.parse_options()

        self.setup_logging()

    def setup_logging(self, target_log=None):
        if target_log is None:
            target_log = log
        old = logging.getLevelName(target_log.level)
        new = logging.getLevelName(self.verbosity)
        target_log.setLevel(self.verbosity)
        log.debug(
            "logging level for %s changed from %s to %s ", target_log.name, old, new
        )

    def add_options(self):
        levels = ", ".join([str(lvl) for lvl in LOG_LEVELS])
        self.parser.add_argument(
            "-v",
            "--verbose",
            help="Set the verbosity {" + levels + "}",
            type=self.validate_verbosity,
        )

    def validate_verbosity(self, value):
        # FIXME use enum.Enum - already in gppw.py
        try:
            value = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError("verbosity is not an integer")
        if value not in LOG_LEVELS:
            raise argparse.ArgumentTypeError("verbosity level not from expected range")
        return value

    def parse_options(self):
        self.args = self.parser.parse_args()
        if self.args.verbose is not None:
            self.verbosity = self.args.verbose

    def run(self):
        raise NotImplementedError("The method 'run' has not bee implemented!")


@contextmanager
def cd(new_path):
    """
    kudos to:
    https://stackoverflow.com/questions/431684/how-do-i-change-the-working-directory-in-python/13197763#13197763
    """
    old_path = os.getcwd()
    log.debug("Save old path: %s", old_path)
    try:
        log.debug("Change directory to: %s", new_path)
        # no yield for now, as there is no need for additional information
        os.chdir(new_path)
        yield old_path
    finally:
        # the old directory might also be remove, however there isn't
        # good and logical thing to do, so in that case the exception will be
        # thrown
        # FIXME Ceesjan taught to not to use format in logging!!!
        log.debug("Switch back to old path: %s", old_path)
        os.chdir(old_path)


# FIXME rename to load_sdks
# FIXME depends on external configuration
# TODO maybe just load them directly from the submodule and put it on SDKVersion
def load_versions(versions):
    """
    parses 'jc221,jc221' etc.
    returns the supported versions and orders them
    from newest to oldest
    """
    props = configparser.ConfigParser()
    props.read(LIB_DIR / "jcversions.properties")
    known = list(props["SUPPORTED_VERSIONS"])

    filtered = []
    for version in versions:
        if version in known:
            filtered.append(version)

    # sort the values based on the order of JC versions in jcversions.properties
    filtered.sort(key=known.index)

    return filtered[::-1]


class JCVersion(NamedTuple):
    major: int
    minor: int

    @classmethod
    def from_str(cls_obj, string: str) -> "JCVersion":
        # TODO add try/except?
        major = int(string[:2])
        minor = int(string[2:])
        return cls_obj(major=major, minor=minor)

    def __str__(self) -> str:
        return "JavaCard version: %s.%s" % (self.major, self.minor)

    def get_sdks(self) -> List["SDKVersion"]:
        """
        Returns a list of sdks, that are worth trying for the specific card
        """
        sdks = []
        available_sdks = SDKVersion.get_available_sdks()
        for sdk in available_sdks:
            if sdk.major < self.major:
                sdks.append(sdk)
            elif sdk.major == self.major and sdk.minor <= self.minor:
                sdks.append(sdk)

        return sdks


class SDKVersion(NamedTuple):
    major: int
    minor: int
    patch: int
    update: Optional[int]
    # TODO what is 'b' in jc310b43
    b_value: Optional[int]
    # the original string, that was parsed to separate values
    raw: str

    # TODO rename cls_obj to cls
    @classmethod
    def from_str(cls_obj, string: str) -> "SDKVersion":
        string = string.strip().lower()
        # fmt: off
        sdk_regex = re.compile(
                r"((?P<header>jc)"
                r"(?P<major>\d)"
                r"(?P<minor>\d)"
                r"(?P<patch>\d)"
                r"((?P<type>[ub]?)"
                r"(?P<type_value>\d+))?)"
        )
        # fmt: on

        match = sdk_regex.match(string)
        if match is not None:
            major = int(match.group("major"))
            minor = int(match.group("minor"))
            patch = int(match.group("patch"))
            update = None
            b_value = None
            if match.group("type") == "u":
                update = int(match.group("type_value"))
            elif match.group("type") == "b":
                b_value = int(match.group("type_value"))

            return cls_obj(
                major=major,
                minor=minor,
                patch=patch,
                update=update,
                b_value=b_value,
                raw=string,
            )

    @classmethod
    def from_list(cls, string: str, sep: str = ",") -> List["SDKVersion"]:
        sdks = []
        for part in [x.strip() for x in string.split(sep=sep)]:
            sdks.append(cls.from_str(part))

        return sdks

    def __str__(self) -> str:
        output = "%s.%s%s." % (self.major, self.minor, self.patch)
        if self.update:
            output += "u%s" % self.update
        elif self.b_value:
            output += "b%s" % self.b_value
        return output

    # TODO load only once and get them from the class afterwards
    @classmethod
    def get_available_sdks(cls) -> List["SDKVersion"]:
        sdks = []
        properties = configparser.ConfigParser()
        properties.read(LIB_DIR / "jcversions.properties")
        for version, _ in properties["SUPPORTED_VERSIONS"].items():
            sdks.append(SDKVersion.from_str(version))

        return sdks

    # TODO missing other comparison methods
    def __eq__(self, other) -> bool:
        result = self.major == other.major
        result = result and self.minor == other.minor
        result = result and self.patch == other.patch
        result = result and self.update == other.update
        result = result and self.b_value == other.b_value
        return result


if __name__ == "__main__":
    app = CommandLineApp()
    app.run()
