import subprocess


def check_ant_is_installed():
    output = subprocess.check_output(["ant", "-version"], stdout=subprocess.PIPE)

    assert output.decode("utf8").startswith("Apache Ant(TM)")
