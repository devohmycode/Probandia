"""tools/ci_local.py: the plan read from ci.yml, the commands, the bilan. No CI is run."""
import importlib.util
import os
import tempfile
import unittest

from tests import ROOT


def load_tool():
    spec = importlib.util.spec_from_file_location("ci_local", os.path.join(ROOT, "tools", "ci_local.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ci = load_tool()


def workflow():
    from probandia.util import yamlio

    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as fh:
        return yamlio.loads(fh.read())


class Expressions(unittest.TestCase):
    def test_status_functions(self):
        context = {"github": {"ref": "refs/heads/master"}}
        self.assertTrue(ci.condition("${{ !cancelled() }}", context, failed=True))
        self.assertTrue(ci.condition("always()", context, failed=True))
        self.assertTrue(ci.condition("failure()", context, failed=True))
        self.assertFalse(ci.condition("success()", context, failed=True))
        self.assertTrue(ci.condition(None, context, failed=False))
        self.assertFalse(ci.condition(None, context, failed=True))

    def test_a_condition_without_status_function_means_success_too(self):
        context = {"github": {"ref": "refs/heads/master"}}
        self.assertTrue(ci.condition("github.ref == 'refs/heads/master'", context, failed=False))
        self.assertFalse(ci.condition("github.ref == 'refs/heads/master'", context, failed=True))

    def test_the_macos_exclusion(self):
        text = "${{ github.ref == 'refs/heads/master' && 'none' || 'macos-latest' }}"
        self.assertEqual(ci.interpolate(text, {"github": {"ref": "refs/heads/master"}}), "none")
        self.assertEqual(ci.interpolate(text, {"github": {"ref": "refs/pull/3/merge"}}), "macos-latest")

    def test_an_unknown_function_or_context_stops(self):
        with self.assertRaises(ci.Unsupported):
            ci.evaluate("hashFiles('x')", {})
        with self.assertRaises(ci.Unsupported):
            ci.evaluate("secrets.TOKEN", {"github": {}})


class ThePlanOfCiYml(unittest.TestCase):
    def test_every_step_of_ci_yml_is_understood(self):
        combos = ci.plan(workflow())
        self.assertTrue(combos)
        kinds = {s.kind for c in combos for s in c.steps}
        self.assertEqual(kinds, {"checkout", "python", "node", "run"})

    def test_the_matrix_of_master(self):
        names = [c.name for c in ci.plan(workflow())]
        self.assertEqual(sorted(n for n in names if n.startswith("test ")), sorted([
            "test (windows-latest, 3.11)", "test (windows-latest, 3.14)",
            "test (ubuntu-latest, 3.11)", "test (ubuntu-latest, 3.12)", "test (ubuntu-latest, 3.13)",
            "test (ubuntu-latest, 3.14)", "test (macos-latest, 3.14)"]))
        self.assertEqual(sorted(n for n in names if n.startswith("tui ")), sorted([
            "tui (windows-latest, 3.11)", "tui (windows-latest, 3.14)", "tui (ubuntu-latest, 3.11)",
            "tui (ubuntu-latest, 3.14)", "tui (macos-latest, 3.14)"]))
        self.assertIn("gedcom", names)

    def test_macos_runs_on_master_only(self):
        names = [c.name for c in ci.plan(workflow(), ref="refs/heads/sprint/x")]
        self.assertFalse([n for n in names if "macos" in n])
        self.assertEqual(len(names), 11)

    def test_what_runs_here(self):
        chosen, absent = ci.select(ci.plan(workflow()))
        self.assertEqual(len(chosen), 11)
        self.assertEqual(sorted(c.name for c in absent), ["test (macos-latest, 3.14)", "tui (macos-latest, 3.14)"])
        gedcom = next(c for c in chosen if c.job == "gedcom")
        self.assertEqual((gedcom.place, gedcom.python, gedcom.id), ("windows", "3.12", "gedcom-windows-3.12"))
        self.assertEqual(len({c.id for c in chosen}), 11)

    def test_filters(self):
        combos = ci.plan(workflow())
        chosen, _ = ci.select(combos, jobs=["test"], places=["windows"], pythons=["3.14"])
        self.assertEqual([c.id for c in chosen], ["test-windows-3.14"])
        chosen, _ = ci.select(combos, jobs=["test", "gedcom"], pythons=["3.13"])
        self.assertEqual(sorted(c.id for c in chosen), ["gedcom-windows-3.12", "test-ubuntu-3.13"])
        chosen, absent = ci.select(combos, places=["ubuntu"])
        self.assertEqual(len(chosen), 6)
        self.assertFalse([c for c in chosen if c.job == "gedcom"])

    def test_the_shell_of_each_runner(self):
        combos = {c.id: c for c in ci.plan(workflow())}
        help_step = combos["test-windows-3.14"].steps[2]
        self.assertEqual((help_step.name, help_step.shell), ("Help runs with no package installed", "pwsh"))
        self.assertEqual(combos["test-ubuntu-3.14"].steps[2].shell, "bash-e")
        tests = next(s for s in combos["test-windows-3.11"].steps if s.name.startswith("Unit and integration"))
        self.assertEqual(tests.shell, "bash")
        self.assertIn("ResourceWarning", tests.script)
        self.assertIn("python tools/run_tests.py -v 2>&1 | tee", tests.script)   # shared out, all its output
        # the gedcom job keeps the shell of its runner (Ubuntu) when it runs under Windows
        self.assertEqual({s.shell for s in combos["gedcom-windows-3.12"].steps if s.kind == "run"}, {"bash-e"})

    def test_the_checks_after_the_tests_run_even_when_the_tests_fail(self):
        steps = next(c for c in ci.plan(workflow()) if c.id == "test-ubuntu-3.12").steps
        index = next(i for i, s in enumerate(steps) if s.name.startswith("Unit and integration"))
        after = steps[index + 1:]
        self.assertGreaterEqual(len(after), 3)
        for step in after:
            self.assertTrue(ci.condition(step.condition, {"github": {}}, failed=True), step.name)
        drift = next(s for s in after if "make_sample_project" in s.script)
        self.assertIn("git status --porcelain -- tests/sample-project tests/sample-project-gps", drift.script)

    def test_an_unknown_key_or_action_stops(self):
        flow = {"jobs": {"x": {"runs-on": "ubuntu-latest", "steps": [{"run": "true", "working-directory": "a"}]}}}
        with self.assertRaises(ci.Unsupported):
            ci.plan(flow)
        flow = {"jobs": {"x": {"runs-on": "ubuntu-latest", "steps": [{"uses": "actions/cache@v4"}]}}}
        with self.assertRaises(ci.Unsupported):
            ci.plan(flow)

    def test_include_adds_or_extends(self):
        job = {"strategy": {"matrix": {"os": ["a", "b"], "py": ["1"],
                                       "exclude": [{"os": "b"}],
                                       "include": [{"os": "a", "extra": "x"}, {"os": "c", "py": "2"}]}}}
        combos, keys = ci.expand_matrix(job, {"github": {}})
        self.assertEqual(keys, ["os", "py"])
        self.assertEqual(combos, [{"os": "a", "py": "1", "extra": "x"}, {"os": "c", "py": "2"}])


class Commands(unittest.TestCase):
    def step(self, shell, script="python -V\n", env=None):
        return ci.Step(number=5, name="s", kind="run", script=script, shell=shell, env=env or {})

    def test_windows(self):
        bash, pwsh = r"C:\Program Files\Git\bin\bash.exe", r"C:\pwsh\pwsh.exe"
        script = r"C:\ci\run\test-windows-3.14.steps\05.sh"
        self.assertEqual(ci.windows_run_argv(self.step("bash"), script, bash, pwsh),
                         [bash, "--noprofile", "--norc", "-eo", "pipefail", "C:/ci/run/test-windows-3.14.steps/05.sh"])
        self.assertEqual(ci.windows_run_argv(self.step("bash-e"), script, bash, pwsh)[1:3], ["-e", script.replace("\\", "/")])
        argv = ci.windows_run_argv(self.step("pwsh"), r"C:\ci\05.ps1", bash, pwsh)
        self.assertEqual(argv[0], pwsh)
        self.assertEqual(argv[-1], r". 'C:\ci\05.ps1'")

    def test_the_powershell_script_exits_with_the_last_code(self):
        text = ci.script_text(self.step("pwsh"))
        self.assertTrue(text.startswith("$ErrorActionPreference = 'stop'\n"))
        self.assertTrue(text.endswith("{ exit $LASTEXITCODE }\n"))
        self.assertEqual(ci.script_text(self.step("bash")), "python -V\n")
        self.assertEqual(ci.script_name(self.step("pwsh")), "05.ps1")

    def test_windows_environment(self):
        base = {"PATH": r"C:\Windows", "PROBANDIA_LANGUAGE": "fr", "CLAUDECODE": "1", "PYTHONPATH": "x",
                "VIRTUAL_ENV": "y", "HOME": "h"}
        layout = {"tmp": r"C:\r\c\tmp", "src": r"C:\r\c\src", "venv": r"C:\r\c\venv", "summary": r"C:\r\c.summary.md"}
        env = ci.windows_env(base, layout, True, {"X": "1"})
        for gone in ("PROBANDIA_LANGUAGE", "CLAUDECODE", "PYTHONPATH"):
            self.assertNotIn(gone, env)
        self.assertEqual(env["VIRTUAL_ENV"], r"C:\r\c\venv")
        self.assertTrue(env["PATH"].startswith(os.path.join(r"C:\r\c\venv", "Scripts") + ";"))
        self.assertEqual((env["CI"], env["RUNNER_TEMP"], env["X"], env["HOME"]), ("true", "C:/r/c/tmp", "1", "h"))
        self.assertEqual(env["CI_LOCAL_NO_TIMING"], "1")   # the times of the TUI, measured on a calm machine
        self.assertNotIn("VIRTUAL_ENV", ci.windows_env(base, layout, False, {}))

    def test_wsl_path(self):
        self.assertEqual(ci.wsl_path(r"C:\Users\Gildas\probandia-ci\r\a.tar"), "/mnt/c/Users/Gildas/probandia-ci/r/a.tar")
        self.assertEqual(ci.wsl_path("D:/x y/z"), "/mnt/d/x y/z")
        with self.assertRaises(ValueError):
            ci.wsl_path("/home/x")

    def test_wsl(self):
        script = ci.wsl_run_script(self.step("bash", env={"PROBANDIA_SESSION": "ci"}), "20261013-120000",
                                   "test-ubuntu-3.12", r"C:\ci\r\test-ubuntu-3.12.summary.md", True,
                                   r"C:\ci\r\test-ubuntu-3.12.steps\05.sh")
        argv = ci.wsl_argv(script)
        self.assertEqual(argv[:6], ["wsl.exe", "-d", "Ubuntu-24.04", "--exec", "bash", "-lc"])
        lines = argv[6].splitlines()
        self.assertEqual(lines[1], 'D="$HOME/probandia-ci/20261013-120000/test-ubuntu-3.12"')
        self.assertIn('export VIRTUAL_ENV="$D/venv" PATH="$D/venv/bin:$PATH"', lines)
        self.assertIn("export PROBANDIA_SESSION=ci", lines)
        self.assertIn("GITHUB_STEP_SUMMARY=/mnt/c/ci/r/test-ubuntu-3.12.summary.md CI_LOCAL_NO_TIMING=1", argv[6])
        self.assertIn("/mnt/*) ;;", argv[6])   # the Windows folders leave PATH
        self.assertEqual(lines[-2:], ['cd "$D/src"',
                                      "exec bash --noprofile --norc -eo pipefail /mnt/c/ci/r/test-ubuntu-3.12.steps/05.sh"])
        before = ci.wsl_run_script(self.step("bash-e"), "r1", "c1", r"C:\s.md", False, r"C:\a b\05.sh")
        self.assertNotIn("VIRTUAL_ENV", before)
        self.assertIn("exec bash -e '/mnt/c/a b/05.sh'", before)

    def test_wsl_checkout_and_python(self):
        checkout = ci.wsl_checkout_script("r1", "test-ubuntu-3.11", r"C:\ci\r1\source.tar")
        self.assertIn('tar -xf /mnt/c/ci/r1/source.tar -C "$D/src"', checkout)
        self.assertIn("git -c init.defaultBranch=master init -q", checkout)
        self.assertIn("commit -q", checkout)
        self.assertIn("uv venv --seed --python-preference only-managed --python 3.11 venv",
                      ci.wsl_python_script("r1", "c", "3.11"))
        with self.assertRaises(ValueError):
            ci.wsl_checkout_script("r1; rm -rf /", "c", r"C:\x.tar")


class Source(unittest.TestCase):
    def test_ls_files(self):
        text = "100644 aaa 0\tREADME.md\x00100755 bbb 0\ttools/x.sh\x00120000 ccc 0\tlink\x00"
        self.assertEqual(ci.parse_ls_files(text), {"README.md": "100644", "tools/x.sh": "100755", "link": "120000"})

    def test_the_tar_keeps_modes_and_skips_deleted_files(self):
        import tarfile

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "tools"))
            for name in ("a.txt", os.path.join("tools", "x.sh")):
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as fh:
                    fh.write("x\n")
            tar_path = os.path.join(tmp, "s.tar")
            count = ci.write_working_tree(tmp, [("a.txt", "100644"), ("gone.txt", "100644"), ("tools/x.sh", "100755")],
                                          tar_path)
            self.assertEqual(count, 2)
            with tarfile.open(tar_path) as tar:
                modes = {m.name: m.mode for m in tar.getmembers()}
            self.assertEqual(modes, {"a.txt": 0o644, "tools/x.sh": 0o755})

    def test_the_local_list_of_forbidden_names_goes_with_the_copy(self):
        import tarfile

        with tempfile.TemporaryDirectory() as tmp:
            tar_path = os.path.join(tmp, "s.tar")
            ci.write_working_tree(tmp, [], tar_path)
            self.assertFalse(ci.add_private_names(tar_path, tmp))   # no list here: nothing added
            os.makedirs(os.path.join(tmp, "private"))
            with open(os.path.join(tmp, "private", "forbidden-names.txt"), "w", encoding="utf-8") as fh:
                fh.write("hugo-invente\n")
            self.assertTrue(ci.add_private_names(tar_path, tmp))
            with tarfile.open(tar_path) as tar:
                self.assertEqual(tar.getnames(), ["private/forbidden-names.txt"])


class Bilan(unittest.TestCase):
    def result(self, name, status, failed_step=None):
        steps = [{"number": 1, "name": "Check out", "status": "ok", "seconds": 1.0, "exit": 0}]
        if failed_step:
            steps.append({"number": 5, "name": failed_step, "status": status, "seconds": 300.0, "exit": 1})
        return {"id": name, "name": name, "status": status, "seconds": 400.0, "log": f"C:/r/{name}.log",
                "steps": steps}

    def data(self, *results):
        return {"run": "20261013-120000", "source": "working tree", "seconds": 812.0, "combinations": list(results),
                "absent": [{"name": "test (macos-latest, 3.14)", "why": "no macos-latest on this machine"}]}

    def test_green(self):
        data = self.data(self.result("test (windows-latest, 3.14)", "ok"), self.result("gedcom", "ok"))
        self.assertEqual(ci.bilan_exit_code(data), 0)
        text = ci.format_bilan(data)
        self.assertIn("ok    test (windows-latest, 3.14)", text)
        self.assertIn("--    test (macos-latest, 3.14)", text)
        self.assertTrue(text.rstrip().endswith("RESULT=OK every combination is green (13 min 32 s)"))

    def test_one_red_combination(self):
        data = self.data(self.result("test (windows-latest, 3.14)", "ok"),
                         self.result("test (ubuntu-latest, 3.12)", "fail", "Unit and integration tests"))
        self.assertEqual(ci.bilan_exit_code(data), 1)
        text = ci.format_bilan(data)
        self.assertIn('FAIL  test (ubuntu-latest, 3.12)', text)
        self.assertIn('step 5 "Unit and integration tests" (exit 1)', text)
        self.assertIn("RESULT=FAIL 1 of 2 combinations not green", text)

    def test_interrupted_and_empty(self):
        self.assertEqual(ci.bilan_exit_code(self.data(self.result("tui", "interrupted", "x"))), 130)
        self.assertEqual(ci.bilan_exit_code(self.data()), 1)

    def test_written_then_read(self):
        data = self.data(self.result("gedcom", "ok"))
        with tempfile.TemporaryDirectory() as tmp:
            ci.write_bilan(tmp, data)
            self.assertEqual(ci.read_bilan(tmp), data)
            with open(os.path.join(tmp, "bilan.txt"), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), ci.format_bilan(data))

    def test_durations(self):
        self.assertEqual(ci.duration(4.25), "4.2 s")
        self.assertEqual(ci.duration(452), "7 min 32 s")
        self.assertEqual(ci.duration(None), "-")


class Quick(unittest.TestCase):
    def choose(self, *changed):
        return ci.quick_select(ci.plan(workflow()), list(changed))

    def test_a_sprint_runs_two_test_combinations(self):
        chosen, left, full = self.choose("src/probandia/verify.py", "locales/fr/LC_MESSAGES/probandia.po")
        self.assertEqual(full, [])
        self.assertEqual(sorted(c.id for c in chosen), ["test-ubuntu-3.12", "test-windows-3.14"])
        why = {a["name"]: a["why"] for a in left}
        self.assertEqual(len(left), 9)
        self.assertEqual(why["test (ubuntu-latest, 3.13)"], "quick: the test job on Windows 3.14 and Ubuntu 3.12 only")
        self.assertEqual(why["tui (windows-latest, 3.14)"], "quick: no file of the TUI changed")
        self.assertEqual(why["gedcom"], "quick: no file of the GEDCOM export changed")
        self.assertNotIn("test (macos-latest, 3.14)", why)

    def test_the_tui_and_gedcom_jobs_when_their_files_change(self):
        chosen, left, _ = self.choose("tests/unit/test_tui_app.py")
        self.assertEqual(sorted(c.id for c in chosen), ["test-ubuntu-3.12", "test-windows-3.14", "tui-windows-3.14"])
        self.assertIn({"name": "tui (ubuntu-latest, 3.11)", "why": "quick: one tui combination, Windows 3.14"}, left)
        for path in ("src/probandia/gedcom.py", "tools/validate_gedcom7.mjs", "tests/fixtures/tree/persons.yaml",
                     "src/probandia/cli/export_cmd.py"):
            chosen, _, _ = self.choose(path)
            self.assertIn("gedcom-windows-3.12", [c.id for c in chosen], path)

    def test_the_ci_the_package_or_the_version_call_for_everything(self):
        for path in (".github/workflows/ci.yml", "tools/ci_local.py", "tools/run_tests.py", "pyproject.toml",
                     "run_probandia.py", "src/probandia/__init__.py", "tools/check_wheel.py"):
            chosen, left, full = self.choose("README.md", path)
            self.assertEqual((chosen, left, full), (None, [], [path]))

    def test_the_files_changed_since_the_merge_base(self):
        import subprocess

        def git(*args):
            subprocess.run(["git", *ci.SNAPSHOT_AUTHOR, *args], cwd=tmp, check=True, capture_output=True)

        def write(name):
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as fh:
                fh.write(name)

        with tempfile.TemporaryDirectory() as tmp:
            git("-c", "init.defaultBranch=master", "init", "-q")
            write("a.txt")
            git("add", "a.txt")
            git("commit", "-q", "-m", "base")
            git("checkout", "-q", "-b", "sprint")
            write("b.txt")
            git("add", "b.txt")
            git("commit", "-q", "-m", "sprint")
            git("checkout", "-q", "master")
            write("m.txt")
            git("add", "m.txt")
            git("commit", "-q", "-m", "master moves on")   # not the sprint's
            git("checkout", "-q", "sprint")
            self.assertEqual(ci.changed_files("HEAD", tmp), ["b.txt"])
            write("a.txt.new")
            with open(os.path.join(tmp, "a.txt"), "a", encoding="utf-8") as fh:
                fh.write("more")
            self.assertEqual(ci.changed_files(None, tmp), ["a.txt", "a.txt.new", "b.txt"])

    def test_the_bilan_says_quick(self):
        data = Bilan().data(Bilan().result("test (windows-latest, 3.14)", "ok"))
        data["quick"] = {"base": "master", "changed": 3,
                         "left_out": [{"name": "gedcom", "why": "quick: no file of the GEDCOM export changed"}]}
        text = ci.format_bilan(data)
        self.assertIn("ci-local 20261013-120000 (quick): working tree", text)
        self.assertIn("--quick: 3 file(s) changed since the merge base with master", text)
        self.assertIn("left out: quick: no file of the GEDCOM export changed", text)
        self.assertTrue(text.rstrip().endswith("RESULT=OK quick: every combination is green, 1 left out (13 min 32 s)"))
        data["quick"] = {"base": "master", "changed": 3, "full_because": ["pyproject.toml"]}
        text = ci.format_bilan(data)
        self.assertIn("--quick ran the whole CI: the revision changes pyproject.toml", text)
        self.assertNotIn("(quick)", text)


class Arguments(unittest.TestCase):
    def test_lists(self):
        args = ci.parse_args(["--jobs", "test,tui", "--os", "windows", "--python", "3.11, 3.14"])
        self.assertEqual((args.jobs, args.places, args.python), (["test", "tui"], ["windows"], ["3.11", "3.14"]))
        self.assertIsNone(ci.parse_args([]).jobs)
        self.assertEqual(ci.parse_args([]).parallel, 8)

    def test_refused(self):
        import contextlib
        import io

        for argv in (["--os", "macos"], ["--parallel", "0"], ["--quick", "--jobs", "test"], ["--quick", "--os", "ubuntu"]):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                ci.parse_args(argv)


if __name__ == "__main__":
    unittest.main()
