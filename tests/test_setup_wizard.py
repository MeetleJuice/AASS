"""Headless user-flow checks; release CI also constructs the real Windows Tk UI."""

import json
import sys
import time
from types import SimpleNamespace

import pytest

import setup_wizard as gui
from setup_controller import CommandResult, ControllerError


class Variable:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Widget:
    def __init__(self, *args, **kwargs):
        self.options = kwargs
        self.text = ""
        self.selected = None

    def configure(self, **kwargs):
        self.options.update(kwargs)

    def pack(self, *args, **kwargs):
        pass

    grid = bind = columnconfigure = add = start = stop = see = set = pack
    yview = itemconfigure = pack

    def create_window(self, *args, **kwargs):
        return 1

    def bbox(self, *args):
        return (0, 0, 800, 800)

    def insert(self, _index, text):
        self.text += text

    def index(self, _index):
        return f"{self.text.count(chr(10)) + 1}.0"

    def delete(self, *_args):
        self.text = ""

    def get(self, *_args):
        return self.text

    def select(self, target):
        self.selected = target


class Window(Widget):
    def __init__(self):
        super().__init__()
        self.callbacks = {}
        self.destroyed = False

    title = geometry = minsize = protocol = Widget.pack

    def winfo_screenwidth(self):
        return 1366

    def winfo_screenheight(self):
        return 768

    def after(self, _delay, callback):
        token = len(self.callbacks) + 1
        self.callbacks[token] = callback
        return token

    def after_cancel(self, token):
        self.callbacks.pop(token, None)

    def destroy(self):
        self.destroyed = True


class FakeController:
    def __init__(self, root, *, runtime=True):
        self.runtime = root / "runtime-python"
        if runtime:
            self.runtime.touch()
        self.calls = []
        self.install_calls = 0
        self.task_calls = []
        self.install_error = self.task_error = None
        self.providers = [{"id": "gemini", "key_present": True}]
        self.cloud_result = {"status": "ok"}
        self.cancel_calls = 0

    def json_operation(self, args, **_kwargs):
        self.calls.append(list(args))
        if args[0] == "credentials":
            return {"status": "ok", "providers": self.providers}
        if args[0] == "models":
            return {
                "status": "ok",
                "models": [
                    {"id": "gemini-flash-latest", "label": "Gemini Flash"},
                    {"id": "gemini-other", "label": "Other"},
                ],
            }
        return self.cloud_result if args[0] == "verify-judge" else {"status": "ok"}

    def install(self, callback):
        self.install_calls += 1
        if self.install_error:
            raise self.install_error
        callback("Local tools checked")
        return CommandResult(0, "ready")

    def run_task(self, target, task, callback):
        self.task_calls.append((target, task))
        if self.task_error:
            raise self.task_error
        return CommandResult(0, "passed")

    def cancel(self):
        self.cancel_calls += 1
        return True


@pytest.fixture
def wizard_factory(tmp_path, monkeypatch):
    ttk = SimpleNamespace(
        **{
            name: Widget
            for name in (
                "Frame",
                "Label",
                "Button",
                "Progressbar",
                "Notebook",
                "Combobox",
                "Entry",
                "Scrollbar",
            )
        }
    )
    tk = SimpleNamespace(ttk=ttk, StringVar=Variable, Text=Widget, Canvas=Widget)
    monkeypatch.setitem(sys.modules, "tkinter", tk)

    def make(*, runtime=True, smoke=True, auto_install=False):
        window = Window()
        controller = FakeController(tmp_path, runtime=runtime)
        app = gui.SetupWizard(
            window,
            root=tmp_path,
            controller=controller,
            auto_install=auto_install,
            smoke=smoke,
        )
        return app, controller, window

    return make


def settle(app):
    deadline = time.monotonic() + 3
    while True:
        app.poll()
        if not app.busy and app.events.empty():
            return
        assert time.monotonic() < deadline, "wizard did not finish its asynchronous operation"
        time.sleep(0.005)


def select_model(app):
    app.available = {"gemini"}
    app.provider.set("Gemini")
    app.models = [{"id": "gemini-flash-latest"}]
    app.model.set("gemini-flash-latest")


def test_opening_existing_install_only_detects_keys_and_lists_models(wizard_factory):
    app, controller, window = wizard_factory(smoke=False)
    refresh = next(
        callback for callback in window.callbacks.values() if callback.__name__ == "refresh"
    )
    refresh()
    settle(app)
    assert controller.calls == [["credentials"], ["models", "--service", "gemini"]]
    assert controller.install_calls == 0
    assert not controller.task_calls
    assert app.model.get() == "gemini-flash-latest"
    assert not app.worker_passed and not app.cloud_passed


def test_smoke_mode_never_schedules_install_or_provider_requests(wizard_factory):
    _, controller, window = wizard_factory(smoke=True, auto_install=True)
    assert {callback.__name__ for callback in window.callbacks.values()} == {"poll"}
    assert not controller.calls and not controller.install_calls


def test_startup_without_runtime_gives_one_local_preparation_action(wizard_factory):
    app, controller, window = wizard_factory(smoke=False, runtime=False)
    assert {callback.__name__ for callback in window.callbacks.values()} == {"poll"}
    assert "Prepare" in app.notice.get()
    assert not controller.calls


def test_automatic_install_stays_local_until_explicit_connection_test(wizard_factory):
    app, controller, window = wizard_factory(smoke=False, auto_install=True)
    install = next(
        callback for callback in window.callbacks.values() if callback.__name__ == "install"
    )
    install()
    settle(app)
    assert controller.install_calls == 1
    assert app.local_ready
    assert all(call[0] in {"credentials", "models"} for call in controller.calls)


def test_cloud_failure_keeps_worker_pass_and_retries_only_cloud(wizard_factory):
    app, controller, _ = wizard_factory()
    select_model(app)
    controller.cloud_result = {
        "status": "error",
        "http_status": 404,
        "message": "This model could not be found.",
        "hint": "Reload models and choose an available model.",
    }
    app.check_connections()
    settle(app)
    assert app.worker_passed and not app.cloud_passed
    assert "404" in app.connection_status.get()
    assert "packages do not need reinstalling" in app.log.text
    controller.cloud_result = {"status": "ok"}
    app.check_connections()
    settle(app)
    assert app.cloud_passed
    assert [call[0] for call in controller.calls] == [
        "verify-worker",
        "verify-judge",
        "verify-judge",
    ]
    assert controller.install_calls == 0


def test_only_an_available_model_is_saved_and_stale_preference_is_replaced(wizard_factory):
    app, _, _ = wizard_factory()
    app.provider.set("Gemini")
    app.preferences = {"service": "gemini", "model": "retired-model"}
    app.models_loaded({"status": "ok", "models": [{"id": "gemini-returned"}]})
    path = app.root / ".aass/provider.json"
    assert json.loads(path.read_text()) == {"service": "gemini", "model": "gemini-returned"}
    app.model.set("guessed-model")
    app.model_changed()
    assert json.loads(path.read_text())["model"] == "gemini-returned"


def test_catalog_failure_clears_old_model_and_allows_retry(wizard_factory):
    app, _, _ = wizard_factory()
    select_model(app)
    app.models_loaded({"status": "error", "message": "Quota unavailable", "hint": "Check usage."})
    assert app.model.get() == "" and app.models == []
    assert "Quota" in app.notice.get()
    app.load_models()
    settle(app)
    assert app.model.get() == "gemini-flash-latest"


def test_refresh_removes_stale_selection_when_credential_file_no_longer_has_key(wizard_factory):
    app, controller, _ = wizard_factory()
    select_model(app)
    app.worker_passed = app.cloud_passed = True
    controller.providers = []
    app.refresh()
    settle(app)
    assert app.model.get() == "" and app.models == []
    assert not app.worker_passed and not app.cloud_passed
    assert not any(call[0].startswith("verify") for call in controller.calls)


def test_install_launch_error_leaves_window_usable_for_retry(wizard_factory):
    app, controller, window = wizard_factory()
    controller.install_error = ControllerError("launch_failed", "This step could not start.")
    app.install()
    settle(app)
    assert not app.busy and not window.destroyed
    assert "could not start" in app.notice.get()
    assert all(button.options["state"] == "normal" for button in app.buttons)
    controller.install_error = None
    app.install()
    settle(app)
    assert app.local_ready


def test_task_launch_error_is_redacted_and_window_remains_usable(wizard_factory):
    app, controller, window = wizard_factory()
    select_model(app)
    app.target.set(str(app.root.parent / "project"))
    app.task_text.text = "Build a calculator"
    controller.task_error = ValueError("private-key-in-untrusted-exception")
    app.run_task()
    settle(app)
    assert not app.busy and not window.destroyed
    assert "private-key" not in app.notice.get() + app.log.text
    assert "could not finish" in app.notice.get()


@pytest.mark.parametrize("missing", ["key", "catalog_model"])
def test_run_cannot_use_a_stale_provider_or_model(wizard_factory, missing):
    app, controller, _ = wizard_factory()
    select_model(app)
    if missing == "key":
        app.available = set()
    else:
        app.model.set("retired-model")
    app.target.set(str(app.root.parent / "project"))
    app.task_text.text = "Build a calculator"
    app.run_task()
    assert not controller.task_calls
    assert app.tabs.selected == 0


def test_closing_skips_completion_that_would_start_another_operation(wizard_factory):
    app, controller, window = wizard_factory()
    app.busy = app.closing = True
    app.events.put(("done", (app.installed, CommandResult(0, "ready"))))
    app.poll()
    assert window.destroyed
    assert not controller.calls


def test_tk_cannot_open_reports_repair_instructions_without_traceback(monkeypatch, capsys):
    class TclError(Exception):
        pass

    def unavailable():
        raise TclError("private-system-detail")

    monkeypatch.setitem(sys.modules, "tkinter", SimpleNamespace(Tk=unavailable, TclError=TclError))
    assert gui.main([]) == 2
    output = capsys.readouterr().out
    assert "Tcl/Tk" in output and "local_app.py" in output
    assert "private-system-detail" not in output


def test_model_choice_never_invents_a_provider_model():
    assert gui.preferred_model([], "saved") == ""
    assert gui.preferred_model([{"id": "actual-model"}], "retired-model") == "actual-model"
    assert (
        gui.preferred_model([{"id": "gemini-2.5-flash"}, {"id": "gemini-3-flash"}])
        == "gemini-3-flash"
    )


def test_cloud_check_log_identifies_selected_model_and_route(wizard_factory):
    app, controller, _ = wizard_factory()
    select_model(app)
    app.worker_passed = True
    controller.cloud_result = {
        "status": "error",
        "http_status": 404,
        "service": "gemini",
        "model": "gemini-flash-latest",
        "api_route": "generateContent",
        "provider_code": "NOT_FOUND",
        "hint": "Choose another model.",
    }
    app.check_connections()
    settle(app)
    assert "model gemini-flash-latest" in app.log.text
    assert "API: generateContent" in app.log.text
    assert "code: NOT_FOUND" in app.log.text
    assert app.worker_passed and not app.cloud_passed
