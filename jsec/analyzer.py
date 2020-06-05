#!/usr/bin/env python


import argparse

# TODO add docstrings
# pylint: disable = missing-class-docstring, missing-function-docstring, invalid-name, fixme
# FIXME use isort
import configparser
import importlib
import logging
import os
import platform
import re
import sys
from pathlib import Path

from jsec.builder import BaseBuilder
from jsec.executor import BaseAttackExecutor
from jsec.executor import AbstractAttackExecutor
from jsec.gppw import GlobalPlatformProWrapper
from jsec.settings import ATTACKS, DATA
from jsec.utils import CommandLineApp, Error, cd, load_versions
from jsec.utils import JCVersion
from typing import Optional
from jsec.data.jcversion.jcversion import JCVersionExecutor

# from jsec.data.jcversion import

# FIXME use flake8 as --dev dependency and remove some pylints
# FIXME handle error on gp --list
# flake8: noqa [WARN] GPSession - GET STATUS failed for 80F21000024F0000 with 0x6A81 (Function not supported e.g. card Life Cycle State is CARD_LOCKED)

# TODO determine the level of defensive approach? E.g. when guessing emv

# FIXME think through the hierarchy of the different loggers
# TODO put into separate file config
log = logging.getLogger(__file__)
# TODO add handler for printing
handler = logging.StreamHandler()
formatter = logging.Formatter("%(levelname)s:%(asctime)s:%(name)s: %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

# TODO might not work properly for future Python versions
# subprocess .run has changed in 3.7
PY_VERSION_TUPLE = platform.python_version_tuple()
PY_VERSION = platform.python_version()

if int(PY_VERSION[0]) < 3:
    print("Unsupported python version: {}".format(PY_VERSION))
    print("Try using Python 3.6")
    sys.exit(Error.UNSUPPORTED_PYTHON_VERSION)


class PreAnalysisManager:
    # make sure, that all the attacks are build
    # and have the scenario.py or whatever to run them
    def __init__(self, card, gp):
        self.gp = gp
        self.card = card

    def run(self):
        # install the JCVersion applet
        # save the version somewhere
        # FIXME don't hardcode it for a card!
        # put JCVersion into a types.ini
        print("WARNING: Manually setting JCVersion for Card A!!!")
        self.card.jcversion = JCVersion.from_str("0300")  # self.get_jc_version()
        self.card.sdks = self.card.jcversion.get_sdks()

    def get_jc_version(self):
        version = JCVersionExecutor(
            card=self.card, gp=self.gp, workdir=Path(), sdk=None
        ).get_jcversion()
        return version


# FIXME give disclaimer and ask about consent
class App(CommandLineApp):
    APP_DESCRIPTION = """
    [DISCLAIMER] Running this analysis can potentially dammage (brick/lock) your card!
    By using this tool you acknowledge this fact and use the tool on your on risk.
    This tool is meant to be used for analysis and research on spare JavaCards in order
    to infer something about the level of the security of the JavaCard Virtual Machine
    implementation it is running.
    """

    def __init__(self):
        # FIXME group self.args according to meaning
        self.config = None
        self.config_file = None
        self.gp = Optional[GlobalPlatformProWrapper]
        self.card = None
        super().__init__()
        self.setup_logging(log)

    def add_options(self):
        # TODO add option for making copy of the attack CAP files for later investigation
        super().add_options()
        self.parser.add_argument(
            "-c", "--config-file", default="user-config.ini", type=self.validate_config,
        )
        self.parser.add_argument(
            "-r",
            "--rebuild",
            default=False,
            action="store_true",
            help=(
                "When set, each used applet will be rebuild before installing and "
                "running. If no card is present this effectively rebuilds all attacks."
            ),
        )
        self.parser.add_argument(
            "-l",
            "--long-description",
            default=False,
            action="store_true",
            help="Will display long description of the tool and end.",
        )

        self.parser.add_argument(
            "-n",
            "--dry-run",
            default=False,
            action="store_true",
            help="No external programs are called, useful when developing the analyzer",
        )
        # TODO test if argparse defaults are validated
        self.parser.add_argument(
            "-o",
            "--output-dir",
            default=Path("jsec-analysis-result"),
            help="A directory, that will store the results of the analysis",
        )
        # TODO def add options attempting to uninstall all applets, that were installed
        # but this should be the implicit behaviour

    def parse_options(self):
        super().parse_options()
        if self.args.config_file is not None:
            self.config_file = self.args.config_file

        self.dry_run = self.args.dry_run
        if self.dry_run:
            print(
                "[Note] '--dry-run' was set, no external commands are called "
                "and no report is created."
            )

    def validate_config(self, value):
        if not os.path.exists(value):
            raise argparse.ArgumentTypeError(
                "\nError: Can't open the configuration file '{}'. "
                "Does it exists and do you have the permission to read it?".format(
                    value
                )
            )
        return Path(value)

    # TODO unify load_configuration and load_config
    def load_configuration(self):
        self.config = configparser.ConfigParser()
        self.config.read(self.config_file)

    def card_present(self) -> bool:
        # TODO check if card is present based on 'gp --list' output
        # this could be done more cleverly using smartcard module
        # TODO check for multiple cards inserted etc.
        result = self.gp.list()
        if result.stderr.decode().startswith("No smart card readers with a card found"):
            return False
        return True

    def run(self):
        self.load_configuration()

        self.gp = GlobalPlatformProWrapper(
            config=self.config, dry_run=self.dry_run, log_verbosity=self.verbosity,
        )
        if not self.card_present():
            print("No card was recognized. Please, insert a card.")
            sys.exit(1)

        # FIXME make sure we only have one card in the reader
        self.card = Card(gp=self.gp)
        self.gp.card = self.card
        print("Running the pre-analysis..")
        prem = PreAnalysisManager(self.card, self.gp)
        prem.run()
        print("Running the analysis..")
        anam = AnalysisManager(self.card, self.gp, self.config)
        anam.run()
        print("Running the post-analysis..")


class PostAnalysisManager:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def create_output_dir(self) -> Path:
        suffix = 0
        while True:
            if suffix:
                self.output_dir += "-{}".format(suffix)
            try:
                os.mkdir(self.output_dir)
            except FileExistsError:
                log.debug(
                    "The directory '%s' already exists. Updating and adding a suffix",
                    self.output_dir,
                )
                suffix += 1

        return self.output_dir

    def run(self):
        self.create_output_dir()


# TODO add logging everywhere
class CardState:
    # basically a parsed output from `gp --list`
    def __init__(self, raw):
        self.raw = raw
        self.isds = []
        self.pkgs = []
        self.applets = []
        self._items = None
        self.parseable = False

    def _parse_raw(self):
        if self._items is not None:
            # cannot parse again!
            return
        self._items = []

        # fmt: off
        tag = re.compile(
            r"(?P<type>ISD|APP|PKG):\s*"
            r"(?P<aid>[A-Z0-9]+)\s*"
            r"\((?P<state>\w+)\)"
        )
        prop = re.compile(
            r"(?P<name>Privs|Version|Applet):\s*"
            r"(?P<value>.*)"
        )
        # fmt: on

        item = {}
        flag = False
        for line in self.raw.strip().split("\n"):
            line = line.strip()

            if not line:
                continue

            tag_match = tag.match(line)
            if tag_match is not None:
                _type = tag_match.group("type")
                aid = tag_match.group("aid")
                state = tag_match.group("state")

                if flag:
                    item = {}
                item[_type] = {
                    "AID": aid,
                    "STATE": state,
                    "ITEMS": {"Privs": [], "Version": [], "Applet": []},
                }
                self._items.append(item)
                flag = not flag
                continue

            prop_match = prop.match(line)
            if prop_match is not None:
                name = prop_match.group("name")
                value = prop_match.group("value")
                if name == "Privs":
                    # if prop_match.group("value"):
                    values = [x.strip() for x in value.split(",")]
                    item[_type]["ITEMS"][name].extend(values)
                else:
                    item[_type]["ITEMS"][name].append(value)

    def process(self):
        # parse the raw output of `gp --list`
        try:
            self._parse_raw()
            self.parseable = True
        except Exception:
            log.warning("The card state coult not be parsed properly")
            self.parseable = False

        # FIXME the next few lines are ugly, but will do for now
        for item in self._items:
            if list(item.keys()) == ["APP"]:
                self.applets.append(item)
            if list(item.keys()) == ["PKG"]:
                self.pkgs.append(item)
            if list(item.keys()) == ["ISD"]:
                self.isds.append(item)

    def get_all_aids(self):
        aids = []
        for item in self.isds:
            try:
                aids.append(item["ISD"]["AID"])
            except KeyError:
                pass

        for item in self.pkgs:
            try:
                aids.append(item["PKG"]["AID"])
            except KeyError:
                pass

            # FIXME this might not work for multiple applets
            aids.extend(item["PKG"]["ITEMS"]["Applet"])

        for item in self.applets:
            try:
                aids.append(item["AID"])
            except KeyError:
                pass

        return aids


class Card:
    # object representing a card during the analysis
    # basically a card can go from one state to another if a GlobalPlatformCall is performed on it. E.g. listing, installing etc.
    # Being defensies and cautious we can, hopefully log each weird behaviour
    # TODO
    # install an applet
    # execute applet/attack steps
    def __init__(self, gp: GlobalPlatformProWrapper):
        self.states = None
        self.current_state = None
        self.gp = gp
        # self.isds = []
        # self.pkgs = []
        # self.applets = []
        # self.aids = []
        # TODO maybe use named tuples from collections?
        self.jcversion = None

    def add_state(self, state):
        if self.states is None:
            self.states = [state]
        else:
            self.states.append(state)

        self.current_state = state

    # def save_state(self):
    #     proc = self.gp.list()
    #     if proc.returncode != 0:
    #         log.info("Cannot save the state of the card.")
    #         return

    #     raw = proc.stdout.decode("utf8")
    #     state = CardState(raw=raw)
    #     state.process()
    #     self._update(state=state)

    def get_current_aids(self):
        if self.current_state is None:
            self.save_state()

        return self.current_state.get_all_aids()


class AnalysisManager:
    def __init__(self, card, gp, config):
        self.card = card
        self.gp = gp
        self.config = config
        self.attacks = None

    def load_attacks(self):
        registry = configparser.ConfigParser()
        registry_file = Path(DATA / "registry.ini")
        if not registry_file.exists():
            log.error("Missing registry file '%s'", registry_file)
            # TODO how to handle clean exit?
        # FIXME does not fail on missing file, check it before
        registry.read(registry_file)
        return registry

    def run(self):
        self.attacks = self.load_attacks()
        for section in self.attacks.sections():
            log.info("Executing attacks from '%s'", section)
            builder_module = self.attacks[section]["builder"]
            for key, value in self.attacks[section].items():
                # TODO this is ugly and not easy to extend in the future, maybe ditch the
                # idea of ini files and get json?
                if key == "builder":
                    continue
                if self.attacks.getboolean(section, key):
                    AttackBuilder = self.get_builder(
                        attack_name=key, builder_module=builder_module
                    )
                    builder = AttackBuilder(gp=self.gp, workdir=ATTACKS / key)
                    if not builder.uniq_aids(self.card.get_current_aids()):
                        builder.uniqfy()
                        # rebuild the applet
                        # TODO or call build directly? much nicer..
                        builder.execute(BaseBuilder.COMMANDS.build)
                    AttackExecutor = self.get_executor(
                        attack_name=key, builder_module=builder_module
                    )
                    executor = AttackExecutor(
                        card=self.card, gp=self.gp, workdir=ATTACKS / key
                    )
                    executor.execute()

    # FIXME finish loading the builder
    def get_builder(self, attack_name: str, builder_module: str):
        try:
            builder = getattr(
                importlib.import_module(
                    f"jsec.data.attacks.{attack_name}.{attack_name}"
                ),
                "AttackBuilder",
            )
            return builder
        except (ModuleNotFoundError, AttributeError):
            pass

        try:
            builder = getattr(
                importlib.import_module(f"jsec.data.attacks.{builder_module}"),
                "AttackBuilder",
            )
            return builder
        except AttributeError:
            pass
        except ModuleNotFoundError:
            # FIXME handle this
            pass

        return BaseBuilder

    def get_executor(
        self, attack_name: str, builder_module: str
    ) -> AbstractAttackExecutor:
        # first load the executor from the directory of the attack
        try:
            executor = getattr(
                importlib.import_module(
                    # TODO this way we cannot test this method, since the load path is
                    # hardcoded
                    f"jsec.data.attacks.{attack_name}.{attack_name}"
                ),
                "AttackExecutor",
            )
            return executor
        except (ModuleNotFoundError, AttributeError):
            pass

        try:
            executor = getattr(
                importlib.import_module(f"jsec.data.attacks.{builder_module}"),
                "AttackExecutor",
            )
        # TODO maybe add ModuleNotFoundError, but if it is in config.ini it is actually an
        # error - either missing module or should not be in config
        except AttributeError:
            pass

        # then fallback to the type of the attack executor
        # finally base executor, that can (un)install and send APDUs
        return BaseAttackExecutor


if __name__ == "__main__":
    app = App()
    app.run()
