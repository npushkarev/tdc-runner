"""TeamCity service message helpers (2018.1-compatible). Stdlib only."""
import sys


def escape(value: str) -> str:
    out = []
    for ch in str(value):
        if ch == "|":
            out.append("||")
        elif ch == "'":
            out.append("|'")
        elif ch == "\n":
            out.append("|n")
        elif ch == "\r":
            out.append("|r")
        elif ch == "[":
            out.append("|[")
        elif ch == "]":
            out.append("|]")
        else:
            out.append(ch)
    return "".join(out)


def message(name: str, stream=None, **attrs) -> str:
    parts = ["##teamcity[%s" % name]
    for key, value in attrs.items():
        parts.append(" %s='%s'" % (key, escape(value)))
    parts.append("]")
    line = "".join(parts)
    print(line, file=stream or sys.stdout, flush=True)
    return line


def block_opened(name, stream=None):
    return message("blockOpened", stream=stream, name=name)


def block_closed(name, stream=None):
    return message("blockClosed", stream=stream, name=name)


def test_suite_started(name, stream=None):
    return message("testSuiteStarted", stream=stream, name=name)


def test_suite_finished(name, stream=None):
    return message("testSuiteFinished", stream=stream, name=name)


def import_data(type_, path, stream=None):
    return message("importData", stream=stream, type=type_, path=path)


def build_problem(description, stream=None):
    return message("buildProblem", stream=stream, description=description)


def build_status(text, stream=None):
    return message("buildStatus", stream=stream, text=text)


def build_statistic(key, value, stream=None):
    return message("buildStatisticValue", stream=stream, key=key, value=str(value))
