#!/usr/bin/env python

# from jcvmutils.utils import LOG_LEVELS
import configparser
import enum
import logging
import os
import re
import subprocess
import tempfile

from jsec.settings import DATA

# FIXME what if no card/reader is present?

log = logging.getLogger(__file__)
# TODO add handler for printing
handler = logging.StreamHandler()
formatter = logging.Formatter("%(levelname)s:%(asctime)s:%(name)s: %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)


# FIXME put into utils.py
class LogLevels(enum.Enum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


class Diversifier(enum.Enum):
    # TODO what about other diversifiers
    # noqa: E501 # see: https://www.notinventedhere.org/articles/python/how-to-use-strings-as-name-aliases-in-python-enums.html
    UNDETECTED = enum.auto()
    EMV = enum.auto()
    VISA2 = enum.auto()
    NONE = enum.auto()
    KDF3 = enum.auto()

    @classmethod
    def get_flag(cls, diversifier):
        if diversifier == cls.NONE:
            return ""
        if diversifier == cls.UNDETECTED:
            return ""
        if diversifier == cls.EMV:
            return "--emv"
        if diversifier == cls.VISA2:
            return "--visa2"
        if diversifier == cls.KDF3:
            return "--kdf3"

    # TODO rename to something more meaningful
    @classmethod
    def special(cls):
        # create a list of not NONE diversifiers
        return [cls.EMV, cls.VISA2, cls.KDF3]


class GlobalPlatformProWrapper(object):
    DIVERSIFIER_ERROR_MSG = (
        "DO NOT RE-TRY THE SAME COMMAND/KEYS OR YOU MAY BRICK YOUR CARD"
    )
    # fixed bytes when selecting an applet
    SELECT_BYTES = bytes([0x00, 0xA4, 0x04, 0x00])

    def __init__(
        self, config, card_types=None, dry_run=False, log_verbosity=logging.CRITICAL
    ):
        # TODO split by init args and other
        self.verbose = True
        self.debug = True
        self.config = config
        self.card_types = card_types
        self.diversifier = Diversifier.UNDETECTED
        self.gp_path = None
        # TODO dry_run is not implemented
        self.dry_run = dry_run
        self.version = None
        self.atr = None
        self._dump_file_content = None
        # TODO add ready flag

        log.setLevel(log_verbosity)

        # load necessery configurations
        self.process_config()
        self.process_card_types()
        # TODO keep track of temporary files created to remove them
        # at the en
        # or simply create a temporary directory and remove it at the end
        self._temp_files = []

    def gp_prefix(self):
        # TODO 'java' might not work on Windows and could require java.exe
        cmd = [
            "java",
            "-jar",
            self.gp_path,
        ]
        # TODO add the diversifier here, it is probably the safest option
        if self.diversifier != Diversifier.UNDETECTED:
            cmd += [Diversifier.get_flag(self.diversifier)]
        return cmd

    def process_config(self):
        # TODO to re-raise or not to re-raise
        # custom exceptions or configparser exceptions?
        try:
            section = self.config["PATHS"]
        except KeyError:
            log.critical("Config does not contain 'PATHS' section. Please, add it.")
            raise RuntimeError("Incomplete configuration.")

        try:
            self.gp_path = section["gp.jar"]
        except KeyError:
            log.critical("Config [PATHS] section does not contain path to 'gp.jar'.")
            raise RuntimeError("Incomplete configuration.")

    def process_card_types(self):
        if self.card_types is None:
            self.card_types = configparser.ConfigParser()
            self.card_types.read(DATA / "types.ini")

    def determine_diversifier(self):
        log.debug("Try to determine the diversifier for the card.")
        self.load_diversifier_from_config()
        if self.diversifier != Diversifier.UNDETECTED:
            return

        self.guess_diversifier()
        if self.diversifier != Diversifier.UNDETECTED:
            return

        # TODO which configuration file
        log.critical("Cannot determine the card diversifier")
        raise ValueError(
            "Cannot determine the card diversifier. "
            "If you know it, set it directly in the configuration file"
        )

    def load_diversifier_from_config(self):
        log.debug("Loading diversifier value from the configuration")
        try:
            value = self.config["CARD"]["diversifier"]
        except KeyError:
            log.debug("Config does not contain a value for diversifier.")
            # don't set diversifier since we haven't found it in the config
            return

        value = value.strip()
        value = value.upper()
        try:
            self.diversifier = Diversifier[value]
            log.debug(
                "Diversifier '%s' loaded from the configuration", self.diversifier
            )
        except KeyError:
            log.warning("The value '%s' is not recognized as valid diversifier.", value)
            return

    def infer_diversifier(self):
        log.debug("Try to infer the diversifier from predefined list of known cards.")
        if self.atr is None:
            log.info("Cannot infer diversifier, 'self.atr' is None")
            return
        # iterate over know ATR values and load their diversifier
        for known_atr in self.card_types.sections():
            if self.same_atr(self.atr, known_atr):
                try:
                    div = self.card_types[known_atr]["diversifier"]
                    log.info("Missing 'diversifier=value' pair")
                except KeyError:
                    continue

                try:
                    self.diversifier = Diversifier[div]
                    # stop looking for other matches, there shouldn't be any anyway
                    break
                except KeyError:
                    continue

    @staticmethod
    def same_atr(first, second):
        # TODO use smartcard.ATR
        clean_first = first.replace(" ", "").upper()
        clean_second = second.replace(" ", "").upper()
        return clean_first == clean_second

    # TODO when and how to save to database? - probably not here, as this should only handle
    # the GlobalPlatformPro calls
    def run(self, options, dump=False):
        cmd = self.gp_prefix()
        if self.verbose:
            cmd += ["--verbose"]
        if self.debug:
            cmd += ["--debug"]

        # TODO consider using context manager for handling temporary files
        # that need to be used by other projects
        tmp_name = None
        # dump the apdu communication to temporary file
        if dump:
            _, tmp_name = tempfile.mkstemp(prefix="jsec-")
            cmd += ["--dump", tmp_name]

        cmd.extend(options)
        if self.dry_run:
            log.info("--dry-run is set, not calling %s", " ".join(cmd))
            proc = None
        else:
            log.debug("Run the command: %s", " ".join(cmd))
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if tmp_name is not None:
            with open(tmp_name, "r") as f:
                self._dump_file_content = f.read()
            try:
                os.remove(tmp_name)
            except NotImplementedError:
                # TODO log.
                pass

        if proc.returncode == 0:
            log.info("The command '%s' was successful.", " ".join(cmd))
        else:
            log.info("The command '%s' was not successful.", " ".join(cmd))

        return proc

    def guess_diversifier(self):
        # try to avoid bricking the card in case the diversifier
        # has been already detected!
        if self.diversifier != Diversifier.UNDETECTED:
            log.debug(
                "Card diversifier already detected (%s). Not detecting it again.",
                self.diversifier.name,
            )
            return
        # first try `$ gp --list` without diversifier
        proc = self.run(["--list"])
        if proc.returncode == 0:
            self.diversifier = Diversifier.NONE
            log.debug("'%s' diversifier is used.", self.diversifier.name)
            return

        # before running other commmand a potentially harming the card
        # we can try to grep for the ATR in the previous output
        # and compare it to known EMV ATRs
        list_output = proc.stdout.decode("utf8")
        self.atr = self.find_atr(list_output)

        self.infer_diversifier()
        if self.diversifier != Diversifier.UNDETECTED:
            return

        for div in Diversifier.special():
            options = ["--list", Diversifier.get_flag(div)]
            proc = self.run(options)
            output = "\n".join([proc.stdout.decode("utf8"), proc.stderr.decode("utf8")])
            if proc.returncode != 0 or self.DIVERSIFIER_ERROR_MSG in output:
                log.warning(
                    "Tried '%s' as diversifier, but it is not correct", div.name
                )
                continue

            self.diversifier = div
            break

    def read_gp_version(self):
        cmd = self.gp_prefix()
        cmd += ["--version"]

        # FIXME add --dry-run
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # the version of GlobalPlatformPro used during the analysis has a bug in the CLI
        # more information at: https://github.com/martinpaljak/GlobalPlatformPro/issues/217
        if proc.returncode in [0, 1]:
            self.version = proc.stdout.decode("utf8").split("\n")[0]

    def verify_gp(self):
        """
        Calling $ gp --help as a sanity checking, that gp is working properly
        """
        cmd = self.gp_prefix()
        cmd += ["--help"]
        # FIXME add --dry-run
        proc = subprocess.run(cmd)

        if proc.returncode == 0:
            self.works = True

    # def get_atr(self, gp_verbose_output=None):
    #     # be cautious in case we have already an ATR
    #     # no need to call it again and potentially brick the card
    #     if self.atr is not None:
    #         return
    #     # in case we have a verbose gp output we can attempt to match the ATR
    #     if gp_verbose_output is not None:
    #         self.atr = self.find_atr(gp_verbose_output)
    #     # otherwise we match for it from output of '--list' command
    #     cmd = self.gp_prefix()
    #     cmd += ["--list"]
    #     proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    #     # should not matter what the return code is
    #     self.atr = self.find_atr(proc.stdout)

    def find_atr(self, string):
        # fragile and naive way of getting the ATR, but does the job
        match = re.search(r"ATR: ([A-Z0-9]+)", string)
        if match:
            return match.group(1)
        return None

    def install(self, applet_path):
        if not os.path.exists(applet_path):
            log.error("Cannot open or incorrect permission set on: '%s'", applet_path)
        return self.run(["--install", applet_path])

    def uninstall(self, applet_path):
        if not os.path.exists(applet_path):
            log.error("Cannot open or incorrect permission set on: '%s'", applet_path)
        return self.run(["--uninstall", applet_path])

    def list(self):
        options = ["--list"]
        proc = self.run(options=options, dump=False)
        return proc

    def select(self, applet_aid):
        pass

    def apdu(self, payload: bytes, applet_aid: bytes):
        # FIXME ugly mixing ints, lists, bytes
        select = self.SELECT_BYTES + bytes([len(applet_aid)]) + applet_aid
        options = [
            "--apdu",
            select.hex(),
            "--apdu",
            payload.hex(),
        ]
        self.run(options, dump=True)

        if self._dump_file_content:
            communication = self._parse_gp_dump_file(
                raw_content=self._dump_file_content
            )
        return communication[payload.hex().upper()]

    def _parse_gp_dump_file(self, raw_content):
        # TODO this is a bit naive, but hey, who isn't
        com = {}
        lines = iter(raw_content.split("\n"))
        while True:
            try:
                line = next(lines)
                if line.startswith("# Sent"):
                    send = next(lines).strip()
                    # consume the line with a comment
                    next(lines)
                    response = next(lines)
                    payload = response[:-4]
                    status = response[-4:]
                    com[send] = {
                        "payload": payload,
                        "status": status,
                    }
            except StopIteration:
                break

        return com


if __name__ == "__main__":
    # this part is not meant to be run standalone, but it is here for the
    # ease of development and testing
    import argparse
    import logging

    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config-file", default="config.ini")
    parser.add_argument("-t", "--card-types-file", default="types.ini")

    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read(args.config_file)

    card_types = configparser.ConfigParser()
    card_types.read(args.card_types_file)

    gp = GlobalPlatformProWrapper(
        config=config, card_types=card_types, log_verbosity=logging.DEBUG
    )
    gp.determine_diversifier()
