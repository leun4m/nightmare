#!/usr/bin/env python3
# -*- coding:utf-8 -*-

"""
Specification for a single Test-Case. (see :py:class:`Test`)
"""

from typing import Optional, Union, List, Set, Tuple, Callable

import os
import re
import sys
import signal
import difflib
import subprocess
import pathlib

from enum import Enum

import threading

from .utils import TermColor, logger


class TestState(Enum):
    """
    Enumeration of all possible states of a :py:class:`Case`
    """

    Success = 0
    """The test was successful"""
    Fail = 1
    """The test has failed"""
    Error = 2
    """The test has produced an error"""
    Assertion = 3
    """The test has produced a assertion"""
    SegFault = 4
    """The test has produced a segmentation fault"""
    InfoOnly = 5
    """Display only the test information"""
    Timeout = 6
    """The test has timed out"""
    Waiting = 7
    """The test awaits execution"""
    Disabled = 8
    """Disables the test"""
    Clean = 10
    """BadWord come clean"""
    BadWord = 11
    """A BadWord was detected"""

    def __str__(self):
        return {
            TestState.Waiting: TermColor.colorText(" WAITING ", TermColor.White),
            TestState.Success: TermColor.colorText(" SUCCESS ", fg=TermColor.Black, bg=TermColor.Green),
            TestState.Fail: TermColor.colorText(" FAIL ", fg=TermColor.Black, bg=TermColor.Red),
            TestState.Error: TermColor.colorText(" ERROR ", fg=TermColor.Black, bg=TermColor.Red, style=TermColor.Bold),
            TestState.SegFault: TermColor.colorText(" SEGFAULT ", fg=TermColor.Black, bg=TermColor.Yellow),
            TestState.Assertion: TermColor.colorText(
                " ASSERTION ", fg=TermColor.Black, bg=TermColor.Yellow, style=TermColor.Bold
            ),
            TestState.InfoOnly: TermColor.colorText(" INFO ", TermColor.White),
            TestState.Timeout: TermColor.colorText(" TIMEOUT ", TermColor.Purple),
            TestState.Disabled: TermColor.colorText(" DISABLED ", TermColor.Blue),
            TestState.Clean: TermColor.colorText(" CLEAN ", fg=TermColor.White, bg=TermColor.Green, style=TermColor.Bold),
            TestState.BadWord: TermColor.colorText(" BADWORD ", fg=TermColor.Yellow, bg=TermColor.Red, style=TermColor.Bold),
        }.get(self, TermColor.colorText(" UNKNOWN ", TermColor.Yellow))

    def __int__(self):
        return int(self.value)


StreamOutput = Optional[Union[str, int]]
"""
The output of a program is either a string (for stdout and stderr)
or an integer (for the return code).
If no output is captured, it may also be None.
"""
Stringified = List[str]
"""
Stringified data are multiple lines of text, represented as a
list of strings.
"""
ExpectationFunc = Callable[[StreamOutput], bool]
"""
An expectation function takes the output of a stream and validates it.
"""
ExpectationT = Optional[Union["Expectation", "Stringifier", ExpectationFunc, List["ExpectationT"], Set["ExpectationT"], str]]
"""
Try to formulate a type for a valid Expectation that can be handled by
:py:class:`Test`.

Currently the following types can be handled:

- Expectation object
- Stringifier object
- plain string
- A lambda function taking a single string parameter, returning a boolean
- A List or a set of all of the above (recursive)
"""


class Command:
    """
    Wrapper for shell commands.

    Executes and buffers the output of a shell command.
    """

    def __init__(self, cmd: str, binary=False):
        self.cmd = cmd
        self.out = ""
        self.err = ""
        self.ret = 0
        self.killed = False
        self.binary = binary

    def commandFunc(self):
        """
        Creates a new subprocess and buffers stdout and stderr.
        """
        self.proc = subprocess.Popen(
            self.cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            universal_newlines=not self.binary,
            shell=True,
            cwd=os.getcwd(),
        )
        self.out, self.err = self.proc.communicate()
        self.ret = self.proc.wait()

    def execute(self, timeout: float) -> TestState:
        """
        Executes the command in a new thread.

        If the process takes longer than the specified timeout,
        the process will be killed.
        """
        self.proc = None
        self.thread = threading.Thread(target=self.commandFunc)
        self.thread.start()
        self.thread.join(timeout)
        if self.proc is not None and self.proc.poll() is None:
            if sys.platform == "win32":
                subprocess.Popen(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)]).communicate()
            else:
                childProc = int(
                    subprocess.check_output(f"pgrep -P {self.proc.pid}", shell=True, universal_newlines=True).strip()
                )
                os.kill(childProc, signal.SIGKILL)
                if self.proc.poll() is None:
                    os.kill(self.proc.pid, signal.SIGTERM)
                # os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            return TestState.Timeout
        return TestState.Success


class Expectation:
    """
    More complex test cases can be constructed by using a specialized
    Expectation. Instead of comparing two strings, the Expectation is
    called as a function with a single argument: the output.

    The Expectation can then run whatever check necessary to validate
    the output. An Expectation should return a boolean value, indicating
    whether the output is valid or not.
    """

    def __call__(self, out: StreamOutput) -> bool:
        return True


class ExpectFile(Expectation):
    """
    Standard Expectation to compare the output against the contents of
    a file.
    """

    def __init__(self, fname: os.PathLike):
        self.exp = open(fname, "rb").read()

    def __call__(self, out: StreamOutput) -> bool:
        return self.exp == out

    def __str__(self):
        return self.exp


class Regex(Expectation):
    """
    Syntactic sugar Expectation to represent a regular expression.
    """

    def __init__(self, regex: str):
        self.regex = re.compile(regex, re.IGNORECASE)

    def __call__(self, out: StreamOutput) -> bool:
        return self.regex.match(str(out)) != None


class Contains(Expectation):
    """
    Syntactic sugar Expectation for finding multiple texts in the output
    """

    def __init__(self, *texts: str):
        self.texts = texts

    def __call__(self, out: StreamOutput) -> bool:
        return all(text in out for text in self.texts)


class ContainsNot(Expectation):
    """
    Syntactic sugar Expectation for finding multiple texts in the output
    """

    def __init__(self, *texts: str):
        self.texts = texts

    def __call__(self, out: StreamOutput) -> bool:
        return all(text not in out for text in self.texts)


class Startswith(Expectation):
    """
    Syntactic sugar Expectation for finding multiple texts in the output
    """

    def __init__(self, text: str):
        self.text = text

    def __call__(self, out: StreamOutput) -> bool:
        return out.startswith(self.text)


class NonZero(Expectation):
    """
    Syntactic sugar Expectation for return code checking
    """

    def __call__(self, out: StreamOutput) -> bool:
        return int(out) != 0


class Negative(Expectation):
    """
    Syntactic sugar Expectation for return code checking
    """

    def __call__(self, out: StreamOutput) -> bool:
        return int(out) < 0


class Stringifier:
    """
    To give the user better information where the output isn't valid
    a line by line difference can be generated.

    Stringifiers split both the expectation as well as the output at
    line-breaks and return two lists of strings, which are then passed
    into the difference builder.
    """

    def __init__(self, expectation: str):
        self.exp = expectation

    def __call__(self, output: StreamOutput) -> Tuple[Stringified, Stringified]:
        return self.exp.strip().splitlines(), output.strip().splitlines()

    def __str__(self):
        return self.exp


class StringifiedFile(Stringifier):
    """
    Stringifier for files. Works for text files only.
    """

    def __init__(self, fname: os.PathLike):
        Stringifier.__init__(self, open(fname).read())


class CompareFiles(Expectation):
    """
    If the DUT creates a file, this Expectation can be used to compare
    the generated file against another.
    The comparison will be binary.
    """

    def __init__(self, expect_file: os.PathLike, out_file: os.PathLike):
        self.expect = expect_file
        self.out = out_file

    def __call__(self, out: StreamOutput) -> bool:
        # Since we want to compare files, actual output is ignored
        expect = open(self.expect, "rb").read()
        out = open(self.out, "rb").read()
        return expect == out


class Test:
    """
    A Test executes a single shell command (the DUT) and compares the
    output against an expectation.

    The easiest form of expectation are simple strings, which must
    match. Leading and trailing whitespace will be ignored.
    If needed the Test can generate the difference between output
    and expectation.

    More complex expectations can be modelled by using a custom
    :py:class:`Expectation`.
    """

    def __init__(
        self,
        DUT=None,
        name="",
        description="",
        command=None,
        stdout=None,
        stderr=None,
        returnCode=None,
        timeout=5.0,
        outputOnFail=False,
        pipe=False,
        diff=None,
        state=TestState.Waiting,
        binary=False,
    ):
        self.name = name
        """The name of the test"""
        self.descr = description
        """The description of the test"""
        self.cmd = command
        """The shell command to be executed"""
        self.expectStdout = stdout
        """The expected output on stdout"""
        self.expectStderr = stderr
        """The expected output on stderr"""
        self.expectRetCode = returnCode
        self.timeout = timeout
        """The expected return code"""
        self.DUT = DUT
        """The Device under Test - could be None"""
        self.output = ""
        """The actual output from stdout"""
        self.error = ""
        """The actual output from stderr"""
        self.retCode = 0
        """The actual return code"""
        self.state = TestState.Waiting
        """The state of the game"""
        self.pipe: bool = pipe
        """Flag, set if the output streams should be piped"""
        self.outputOnFail = outputOnFail
        """Flag, set if the output streams should be piped on failed test"""
        self.diff: bool = diff
        """Flag, show comparison between input and string-expectation"""
        self.timeout: float = timeout
        """Timeout after the DUT gets killed"""
        self.linesep = os.linesep
        """Force a specific line ending"""
        self.ignoreEmptyLines = False
        """Ignore empty lines Flag"""
        self.pipeLimit = 2000
        """Work in binary mode"""
        self.binary: bool = binary

    def lineComparison(self, expLines: Stringified, outLines: Stringified, stream="") -> bool:
        """
        Compares to lines of strings.

        Outputs a colored unified diff on stdout.
        """
        same = True
        if self.ignoreEmptyLines:
            while expLines.count("") > 0:
                expLines.remove("")
            while outLines.count("") > 0:
                outLines.remove("")
        for line in difflib.unified_diff(outLines, expLines, stream, "expectation"):
            col = TermColor.White
            if line.startswith("+"):
                same = False
                col = TermColor.Green
            elif line.startswith("-"):
                same = False
                col = TermColor.Red
            elif line.startswith("@"):
                same = False
                col = TermColor.Cyan
            if self.diff:
                logger.log(TermColor.colorText(line.rstrip(), col))
        return same

    def check(self, exp: ExpectationT, out: Optional[Union[str, int]], stream="returnCode") -> bool:
        """
        Test an output against an expectation.

        - Strings will be compared directly
        - Strings prefixed with 'regex:' will be interpreted as a
          regular expression. The output is valid, if it matches the
          expression.
        - lambda functions and custom :py:class:`Expectation` will be
          executed. The function should return a boolean value
          indicating the validity of the output.
        - Stringifiers will trigger a line by line comparison
        - For lists, each item will be checked individually.
          The output must be valid for all items. (AND)
        - For sets, each item will be checked individually.
          The output must be valid for at least one item. (OR)
        """
        if exp is None:
            return True
        elif isinstance(exp, Stringifier):
            return self.lineComparison(*(exp(out)), stream=stream)
        elif callable(exp) or isinstance(exp, Expectation):
            return exp(out)
        elif isinstance(exp, int) and isinstance(out, int):
            return exp == out
        elif isinstance(exp, list):
            return self.checkList(exp, out)
        elif isinstance(exp, set):
            return self.checkSet(exp, out)
        elif isinstance(exp, bytes):
            return exp == out
        elif isinstance(exp, str):
            if exp.startswith("lambda"):
                f = eval(exp)
                return f(out)
            if exp.startswith("regex:"):
                patCode = re.compile(exp[6:].replace("$n", self.linesep), re.IGNORECASE)
                return patCode.match(str(out)) != None
            else:
                expLines = exp.replace("$n", self.linesep).splitlines()
                outLines = str(out).rstrip().splitlines()
                return self.lineComparison(expLines, outLines, stream)
        return False

    def checkList(self, lst: List[ExpectationT], out: Optional[Union[str, int]]) -> bool:
        """
        Tests a list of expectations against an output
        all elements in the list must match to be successful
        """
        for exp in lst:
            if not self.check(exp, out):
                return False
        return True

    def checkSet(self, st: Set[ExpectationT], out: Optional[Union[str, int]]) -> bool:
        """
        Tests a set of expectations against an output
        one element in the set must match to be successful
        """
        for exp in st:
            if self.check(exp, out):
                return True
        return False

    def pipeOutputStream(self, stream, lines: List[str], color: int):
        bytes = 0
        for line in lines:
            bytes += len(line)
            stream.write(TermColor.colorText(line + " ", fg=color) + "\n")
            if bytes > self.pipeLimit:
                stream.write(TermColor.colorText(f"Stopped after {bytes} Bytes", fg=TermColor.Yellow) + "\n")
                break

    def runCmd(self, command: str):
        """
        Runs the DUT shell command and performs individual checks for
        stdout, stderr and the returncode.

        If requested the output of the command will be piped through
        their respective streams.

        If the execution of the command fails, a detection for
        assertions or segmentation faults will deduce whether or not the
        program terminated correctly or not.
        """
        if "$DUT" in command:
            if self.DUT is None:
                self.state = TestState.Error
                return
            else:
                _cmd = Command(cmd=str(command).replace("$DUT", self.DUT), binary=self.binary)
        else:
            _cmd = Command(cmd=str(command))
        cmdRet = _cmd.execute(self.timeout)
        if cmdRet == TestState.Success:
            self.output = _cmd.out
            self.error = _cmd.err
            self.retCode = _cmd.ret
            if (
                self.check(self.expectRetCode, self.retCode)
                and self.check(self.expectStdout, self.output, "stdout")
                and self.check(self.expectStderr, self.error, "stderr")
            ):
                self.state = TestState.Success
            else:
                if "Assertion" in self.error or "assertion" in self.error:
                    self.state = TestState.Assertion
                elif (
                    "stackdump" in self.error
                    or "coredump" in self.error
                    or "Segmentation Fault" in self.error
                    or self.retCode < 0
                ):
                    self.state = TestState.SegFault
                else:
                    self.state = TestState.Fail
            if (self.pipe) or (self.outputOnFail and self.state is TestState.Fail):
                sys.stdout.write(TermColor.colorText(f"{self.retCode}", fg=TermColor.Yellow) + " ")
                self.pipeOutputStream(sys.stdout, self.output.splitlines(), TermColor.Green)
                self.pipeOutputStream(sys.stderr, self.error.splitlines(), TermColor.Red)
        else:
            self.state = cmdRet

    def run(self) -> TestState:
        """
        Execute this test case.
        """
        if self.state == TestState.Disabled:
            return TestState.Disabled
        if self.state == TestState.InfoOnly:
            if self.descr is None:
                print(f"{self.name}")
            else:
                print(f"{self.name} - {self.descr}")
            return TestState.InfoOnly
        if self.name == "Badword":
            # Bad Word Detection Mode
            # Description holds a matching file patterns
            # Recursive look through the directory of DUT
            # Treat command as a list of Badwords
            words = [re.compile(s) for s in self.cmd]
            searchpath = pathlib.Path(self.DUT).parent
            hits = []
            for fname in searchpath.glob(self.descr):
                with open(fname, "r") as fHnd:
                    for nr, line in enumerate(fHnd.readlines()):
                        for word in words:
                            if word.search(line) is not None:
                                hits.append((os.path.relpath(fname), nr, line.rstrip(), word.pattern))
            if len(hits) > 0:
                for file, lineno, text, pattern in hits:
                    logger.log(f"{TestState.BadWord} {file}[{lineno}]: '{text}' matches '{pattern}'")
                self.state = TestState.BadWord
            else:
                self.state = TestState.Clean
            return self.state
        if self.cmd is not None:
            if isinstance(self.cmd, list):
                for cmd_ in self.cmd:
                    self.runCmd(cmd_)
            else:
                self.runCmd(self.cmd)
        else:
            self.state = TestState.Error
        return self.state

    def __str__(self):
        return self.toString(prefix="")

    def toString(self, prefix="\t") -> str:
        """
        Creates a textual representation of the test.
        The output can be saved to a file.
        """
        fields = []
        fields.append(f"{prefix}\tname = '{self.name:s}'")
        if self.descr is not None and self.descr != "":
            fields.append(f"{prefix}\tdescription = '{self.descr:s}'")
        fields.append(f"{prefix}\tcommand = '{self.cmd:s}'")
        if self.expectStdout is not None:
            fields.append(f'{prefix}\tstdout = """{self.expectStdout}"""')
        if self.expectStderr is not None:
            fields.append(f'{prefix}\tstderr = """{self.expectStderr}"""')
        if self.expectRetCode is not None:
            fields.append(f'{prefix}\treturnCode = "{self.expectRetCode}"')
        if self.timeout is not None:
            fields.append(f"{prefix}\ttimeout = {self.timeout:.1f}")
        return ",\n".join(["Test ("] + fields + [prefix + ")"])


class BadWord(Test):
    def __init__(self, name, description="", path : os.PathLike = None, pattern="", words: List[str] = []):
        self.name = name
        self.descr = description
        self.pattern = pattern
        self.path = path
        self.words = words

    def run(self) -> TestState:
        words = [re.compile(s) for s in self.words]
        if self.path is None:
            searchpath = pathlib.Path(self.path)
        elif hasattr(self, "DUT"):
            searchpath = pathlib.Path(self.DUT).parent
        else:
            searchpath = pathlib.Path(".")
        hits = []
        for fname in searchpath.glob(self.pattern):
            with open(fname, "r") as fHnd:
                for nr, line in enumerate(fHnd.readlines()):
                    for word in words:
                        if word.search(line) is not None:
                            hits.append((os.path.relpath(fname), nr, line.rstrip(), word.pattern))
        if len(hits) > 0:
            for file, lineno, text, pattern in hits:
                logger.log(f"{TestState.BadWord} {file}[{lineno}]: '{text}' matches '{pattern}'")
            self.state = TestState.BadWord
        else:
            self.state = TestState.Clean
        return self.state

    def __str__(self):
        return self.toString(prefix="")

    def toString(self, prefix="\t") -> str:
        """
        Creates a textual representation of the test.
        The output can be saved to a file.
        """
        fields = []
        fields.append(f"{prefix}\tname = '{self.name:s}'")
        if self.descr is not None and self.descr != "":
            fields.append(f"{prefix}\tdescription = '{self.descr:s}'")
        fields.append(f"{prefix}\tcommand = '{self.cmd:s}'")
        if self.expectStdout is not None:
            fields.append(f'{prefix}\tstdout = """{self.expectStdout}"""')
        if self.expectStderr is not None:
            fields.append(f'{prefix}\tstderr = """{self.expectStderr}"""')
        if self.expectRetCode is not None:
            fields.append(f'{prefix}\treturnCode = "{self.expectRetCode}"')
        if self.timeout is not None:
            fields.append(f"{prefix}\ttimeout = {self.timeout:.1f}")
        return ",\n".join(["BadWord ("] + fields + [prefix + ")"])


class TestGroup:
    """
    Groups multiple tests to be counted as a single one.

    This is mainly used for bundleing less important tests, if the
    results of multiple tests are weighted.

    By specifing a predicate, the behavior when deciding if the group
    was successful or not can be adjusted. Default is `all`.
    """

    key = "Group"

    def __init__(self, *tests: Test, name: str = None, predicate: Callable[[List[bool]], bool] = all):
        self.tests = [t for t in tests]
        self._name = name
        self.state = TestState.Waiting
        self.predicate = predicate

    @property
    def name(self) -> str:
        if self._name is None:
            return f"Group of {len(self.tests)} tests"
        return self._name

    @property
    def descr(self) -> Optional[str]:
        return None

    @property
    def cmd(self) -> Optional[str]:
        return " --> ".join(t.cmd for t in self.tests)

    def log_test(self, t, nr=0):
        if t.descr is not None:
            logger.log(f"  {TermColor.colorText('Test', TermColor.Purple)}[{nr: 03}] {t.name} - {t.descr}: {t.state}")
        else:
            logger.log(f"  {TermColor.colorText('Test', TermColor.Purple)}[{nr: 03}] {t.name}: {t.state}")

    def run(self) -> TestState:
        """
        Runs all Test in the group.

        If all
        """
        results = []
        for nr, t in enumerate(self.tests):
            results.append(t.run())
            self.log_test(t, nr)
        self.state = TestState.Success if self.predicate(result == TestState.Success for result in results) else TestState.Fail
        return self.state

    def toString(self, prefix="\t") -> str:
        """
        Creates a textual representation of the testgroup.
        The output can be saved to a file.
        """
        tests = [t.toString(prefix + "\t") for t in self.tests]
        if self._name is not None:
            tests += [f"name='{self.name}'"]
        tests += [f"predicate={self.predicate.__name__}"]
        return f"Group(\n{prefix}\t" + ",\n{prefix}\t".join(tests) + f"\n{prefix})"


class TestAll(TestGroup):
    def __init__(self, *tests: List[Test], name: str = None):
        super.__init__(self, *tests, name=name, predicate=all)


class TestAny(TestGroup):
    def __init__(self, *tests: List[Test], name: str = None):
        super.__init__(self, *tests, name=name, predicate=any)
