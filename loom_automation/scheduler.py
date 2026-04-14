from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from pathlib import Path
import threading
from typing import Any, Callable

from loom_automation.models import LoomImportRequest, ProcessFolderRequest
from loom_automation.workflow import AutomationWorkflow


@dataclass
class SchedulerTaskState:
    enabled: bool
    interval_minutes: int
    last_started_at: str | None = None
    last_finished_at: str | None = None
    last_status: str = "idle"
    last_message: str = ""
    last_result_summary: dict[str, Any] = field(default_factory=dict)
    next_run_at: str | None = None


class AutomationScheduler:
    def __init__(
        self,
        workflow: AutomationWorkflow,
        *,
        enabled: bool,
        meeting_type: str,
        local_folder_enabled: bool,
        local_folder_path: str | None,
        local_folder_minutes: int,
        loom_enabled: bool,
        loom_minutes: int,
        loom_limit: int,
        loom_library_url: str | None,
        active_from: str,
        active_to: str,
        active_weekdays: str,
        settings_path: str | None = None,
    ) -> None:
        self.workflow = workflow
        self.enabled = enabled
        self.meeting_type = meeting_type
        self.local_folder_path = local_folder_path
        self.loom_limit = loom_limit
        self.loom_library_url = loom_library_url
        self.active_from = active_from
        self.active_to = active_to
        self.active_weekdays = active_weekdays
        self.settings_path = Path(settings_path) if settings_path else None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._workflow_lock = threading.Lock()
        self._task_threads: dict[str, threading.Thread | None] = {
            "local_folder": None,
            "loom_import": None,
        }
        self.local_folder = SchedulerTaskState(
            enabled=bool(enabled and local_folder_enabled and local_folder_path),
            interval_minutes=max(1, local_folder_minutes),
        )
        self.loom = SchedulerTaskState(
            enabled=bool(enabled and loom_enabled),
            interval_minutes=max(1, loom_minutes),
        )
        self._apply_schedule_defaults()
        self._load_settings()

    def start(self) -> None:
        if not self.enabled or self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="aicallorder-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            local_folder_state = self.local_folder.__dict__.copy()
            loom_state = self.loom.__dict__.copy()
            local_folder_state["in_progress"] = self._task_is_alive_unlocked("local_folder")
            loom_state["in_progress"] = self._task_is_alive_unlocked("loom_import")
            return {
                "enabled": self.enabled,
                "meeting_type": self.meeting_type,
                "local_folder_path": self.local_folder_path,
                "loom_library_url": self.loom_library_url,
                "active_from": self.active_from,
                "active_to": self.active_to,
                "active_weekdays": self.active_weekdays,
                "tasks": {
                    "local_folder": local_folder_state,
                    "loom_import": loom_state,
                },
            }

    def configure(
        self,
        *,
        enabled: bool,
        meeting_type: str,
        local_folder_enabled: bool,
        local_folder_path: str | None,
        local_folder_minutes: int,
        loom_enabled: bool,
        loom_minutes: int,
        loom_limit: int,
        loom_library_url: str | None = None,
        active_from: str | None = None,
        active_to: str | None = None,
        active_weekdays: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self.enabled = enabled
            self.meeting_type = meeting_type or self.meeting_type
            self.local_folder_path = local_folder_path or None
            self.loom_limit = max(1, loom_limit)
            self.loom_library_url = loom_library_url or self.loom_library_url
            if active_from:
                self.active_from = active_from
            if active_to:
                self.active_to = active_to
            if active_weekdays:
                self.active_weekdays = active_weekdays
            self.local_folder.enabled = bool(enabled and local_folder_enabled and self.local_folder_path)
            self.local_folder.interval_minutes = max(1, local_folder_minutes)
            self.loom.enabled = bool(enabled and loom_enabled)
            self.loom.interval_minutes = max(1, loom_minutes)
            self._apply_schedule_defaults()
            self._save_settings()

        if self.enabled:
            self.start()
        else:
            self.stop()

        return self.status()

    def run_local_folder_now(self) -> dict[str, Any]:
        if not self.local_folder_path:
            return {"scheduled": False, "reason": "Local folder path is not configured."}
        if not self.enabled or not self.local_folder.enabled:
            return {"scheduled": False, "reason": "Local folder scheduler is disabled."}
        return self._launch_task(
            task_name="local_folder",
            task=self.local_folder,
            runner=self._execute_local_folder,
            queued_message="Local folder run queued in background.",
        )

    def run_loom_now(self) -> dict[str, Any]:
        if not self.enabled or not self.loom.enabled:
            return {"scheduled": False, "reason": "Loom scheduler is disabled."}
        return self._launch_task(
            task_name="loom_import",
            task=self.loom,
            runner=self._execute_loom_import,
            queued_message="Loom import queued in background.",
        )

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.utcnow()
            if self.local_folder.enabled and self._is_due(self.local_folder, now) and self._is_active_now():
                self._launch_task(
                    task_name="local_folder",
                    task=self.local_folder,
                    runner=self._execute_local_folder,
                    queued_message="Scheduled local folder run queued in background.",
                )
            if self.loom.enabled and self._is_due(self.loom, now) and self._is_active_now():
                self._launch_task(
                    task_name="loom_import",
                    task=self.loom,
                    runner=self._execute_loom_import,
                    queued_message="Scheduled Loom import queued in background.",
                )
            self._stop.wait(5)

    def _is_due(self, task: SchedulerTaskState, now: datetime) -> bool:
        if not task.next_run_at:
            return False
        try:
            due_at = datetime.fromisoformat(task.next_run_at)
        except ValueError:
            return True
        return now >= due_at

    def _execute_local_folder(self) -> dict[str, Any]:
        task = self.local_folder
        self._mark_started(task)
        try:
            result = self.workflow.process_folder(
                ProcessFolderRequest(
                    folder_path=self.local_folder_path,
                    meeting_type=self.meeting_type,
                ),
                initiated_by="scheduler",
            )
            summary = {
                "processed_count": result.get("processed_count", 0),
                "pipeline": result.get("pipeline"),
            }
            self._mark_finished(task, "success", "Local folder run completed.", summary)
            return {"scheduled": True, **summary}
        except Exception as exc:
            self._mark_finished(task, "error", str(exc), {})
            return {"scheduled": True, "error": str(exc)}

    def _execute_loom_import(self) -> dict[str, Any]:
        task = self.loom
        self._mark_started(task)
        previous_library_url = getattr(self.workflow.loom_client, "library_url", None)
        try:
            if self.loom_library_url:
                self.workflow.loom_client.library_url = self.loom_library_url
            result = self.workflow.import_latest_loom(
                LoomImportRequest(
                    limit=self.loom_limit,
                    meeting_type=self.meeting_type,
                ),
                initiated_by="scheduler",
            )
            summary = {
                "processed_count": result.get("processed_count", 0),
                "pipeline": result.get("pipeline"),
            }
            self._mark_finished(task, "success", "Loom import completed.", summary)
            return {"scheduled": True, **summary}
        except Exception as exc:
            self._mark_finished(task, "error", str(exc), {})
            return {"scheduled": True, "error": str(exc)}
        finally:
            self.workflow.loom_client.library_url = previous_library_url

    def _launch_task(
        self,
        *,
        task_name: str,
        task: SchedulerTaskState,
        runner: Callable[[], dict[str, Any]],
        queued_message: str,
    ) -> dict[str, Any]:
        queued_at = datetime.utcnow().isoformat()
        with self._lock:
            if self._task_is_alive_unlocked(task_name):
                return {
                    "scheduled": False,
                    "reason": f"{self._task_label(task_name)} is already running.",
                    "status": task.last_status,
                    "last_started_at": task.last_started_at,
                    "last_finished_at": task.last_finished_at,
                }
            task.last_status = "queued"
            task.last_message = queued_message
            task.next_run_at = queued_at
            thread = threading.Thread(
                target=self._run_task_thread,
                args=(task_name, runner),
                name=f"aicallorder-{task_name}",
                daemon=True,
            )
            self._task_threads[task_name] = thread
        thread.start()
        return {
            "scheduled": True,
            "background": True,
            "status": "queued",
            "queued_at": queued_at,
            "message": queued_message,
        }

    def _run_task_thread(self, task_name: str, runner: Callable[[], dict[str, Any]]) -> None:
        current_thread = threading.current_thread()
        try:
            with self._workflow_lock:
                runner()
        finally:
            with self._lock:
                if self._task_threads.get(task_name) is current_thread:
                    self._task_threads[task_name] = None

    def _mark_started(self, task: SchedulerTaskState) -> None:
        now = datetime.utcnow().isoformat()
        with self._lock:
            task.last_started_at = now
            task.last_status = "running"
            task.last_message = "Run is in progress."

    def _mark_finished(self, task: SchedulerTaskState, status: str, message: str, summary: dict[str, Any]) -> None:
        now = datetime.utcnow()
        with self._lock:
            task.last_finished_at = now.isoformat()
            task.last_status = status
            task.last_message = message
            task.last_result_summary = summary
            task.next_run_at = (now + timedelta(minutes=task.interval_minutes)).isoformat()

    def _apply_schedule_defaults(self) -> None:
        now = datetime.utcnow().isoformat()
        if self.local_folder.enabled and not self.local_folder.next_run_at:
            self.local_folder.next_run_at = now
        if not self.local_folder.enabled:
            self.local_folder.next_run_at = None
        if self.loom.enabled and not self.loom.next_run_at:
            self.loom.next_run_at = now
        if not self.loom.enabled:
            self.loom.next_run_at = None

    def _load_settings(self) -> None:
        if not self.settings_path or not self.settings_path.exists():
            return
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        self.enabled = bool(payload.get("enabled", self.enabled))
        self.meeting_type = str(payload.get("meeting_type", self.meeting_type))
        self.local_folder_path = payload.get("local_folder_path") or self.local_folder_path
        self.loom_limit = max(1, int(payload.get("loom_limit", self.loom_limit)))
        self.loom_library_url = payload.get("loom_library_url") or self.loom_library_url
        self.active_from = str(payload.get("active_from", self.active_from))
        self.active_to = str(payload.get("active_to", self.active_to))
        self.active_weekdays = str(payload.get("active_weekdays", self.active_weekdays))
        self.local_folder.enabled = bool(payload.get("local_folder_enabled", self.local_folder.enabled) and self.enabled and self.local_folder_path)
        self.local_folder.interval_minutes = max(1, int(payload.get("local_folder_minutes", self.local_folder.interval_minutes)))
        self.loom.enabled = bool(payload.get("loom_enabled", self.loom.enabled) and self.enabled)
        self.loom.interval_minutes = max(1, int(payload.get("loom_minutes", self.loom.interval_minutes)))
        self.local_folder.next_run_at = payload.get("local_folder_next_run_at") or self.local_folder.next_run_at
        self.loom.next_run_at = payload.get("loom_next_run_at") or self.loom.next_run_at
        self._apply_schedule_defaults()

    def _save_settings(self) -> None:
        if not self.settings_path:
            return
        payload = {
            "enabled": self.enabled,
            "meeting_type": self.meeting_type,
            "local_folder_enabled": self.local_folder.enabled,
            "local_folder_path": self.local_folder_path,
            "local_folder_minutes": self.local_folder.interval_minutes,
            "loom_enabled": self.loom.enabled,
            "loom_minutes": self.loom.interval_minutes,
            "loom_limit": self.loom_limit,
            "loom_library_url": self.loom_library_url,
            "active_from": self.active_from,
            "active_to": self.active_to,
            "active_weekdays": self.active_weekdays,
            "local_folder_next_run_at": self.local_folder.next_run_at,
            "loom_next_run_at": self.loom.next_run_at,
        }
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            return

    def _is_active_now(self) -> bool:
        now = datetime.now()
        weekday_map = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        allowed_days = {item.strip().lower() for item in self.active_weekdays.split(",") if item.strip()}
        if allowed_days and weekday_map[now.weekday()] not in allowed_days:
            return False
        start_minutes = self._parse_time_to_minutes(self.active_from, default_minutes=8 * 60)
        end_minutes = self._parse_time_to_minutes(self.active_to, default_minutes=21 * 60)
        current_minutes = now.hour * 60 + now.minute
        if start_minutes <= end_minutes:
            return start_minutes <= current_minutes <= end_minutes
        return current_minutes >= start_minutes or current_minutes <= end_minutes

    def _parse_time_to_minutes(self, value: str, *, default_minutes: int) -> int:
        try:
            hour_text, minute_text = value.strip().split(":", 1)
            hour = max(0, min(23, int(hour_text)))
            minute = max(0, min(59, int(minute_text)))
            return hour * 60 + minute
        except Exception:
            return default_minutes

    def _task_is_alive_unlocked(self, task_name: str) -> bool:
        thread = self._task_threads.get(task_name)
        return bool(thread and thread.is_alive())

    def _task_label(self, task_name: str) -> str:
        if task_name == "local_folder":
            return "Watched folder run"
        return "Loom import"
