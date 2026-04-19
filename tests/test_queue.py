# -*- coding: utf-8 -*-
"""Tests for converter.queue: TaskQueue FIFO, reorder, remove, concurrency."""

import pytest

from converter.ffmpeg.quality import QualityPreset
from converter.ffmpeg.runner import CancelToken, TokenState
from converter.queue import (
    EventType,
    ExecutionEvent,
    TaskQueue,
    auto_concurrency,
    resolve_concurrency,
)
from converter.worker import ConvertTask, TaskKind


def _make_task(fmt: str = "mp4") -> ConvertTask:
    return ConvertTask(kind=TaskKind.VIDEO, files=["a.mp4"], target_format=fmt)


class TestTaskQueue:
    def test_enqueue_dequeue_fifo(self):
        q = TaskQueue()
        q.enqueue(_make_task("mp4"))
        q.enqueue(_make_task("mkv"))
        t1 = q.dequeue()
        assert t1 is not None and t1.target_format == "mp4"
        t2 = q.dequeue()
        assert t2 is not None and t2.target_format == "mkv"
        assert q.dequeue() is None

    def test_is_empty(self):
        q = TaskQueue()
        assert q.is_empty()
        q.enqueue(_make_task())
        assert not q.is_empty()
        q.dequeue()
        assert q.is_empty()

    def test_pending(self):
        q = TaskQueue()
        q.enqueue(_make_task("a"))
        q.enqueue(_make_task("b"))
        q.enqueue(_make_task("c"))
        q.dequeue()
        assert len(q.pending) == 2
        assert q.pending[0].target_format == "b"

    def test_move_up(self):
        q = TaskQueue()
        q.enqueue(_make_task("a"))
        q.enqueue(_make_task("b"))
        q.enqueue(_make_task("c"))
        assert q.move_up(1)
        assert q.pending[0].target_format == "b"
        assert q.pending[1].target_format == "a"

    def test_move_down(self):
        q = TaskQueue()
        q.enqueue(_make_task("a"))
        q.enqueue(_make_task("b"))
        q.enqueue(_make_task("c"))
        assert q.move_down(0)
        assert q.pending[0].target_format == "b"
        assert q.pending[1].target_format == "a"

    def test_remove_pending(self):
        q = TaskQueue()
        q.enqueue(_make_task("a"))
        q.enqueue(_make_task("b"))
        q.enqueue(_make_task("c"))
        assert q.remove_pending(1)
        assert len(q.pending) == 2
        assert q.pending[1].target_format == "c"

    def test_clear(self):
        q = TaskQueue()
        q.enqueue(_make_task())
        q.enqueue(_make_task())
        q.clear()
        assert q.is_empty()
        assert q.total() == 0


class TestConcurrency:
    def test_auto_burn_is_1(self):
        assert auto_concurrency(use_hw=False, is_burn=True) == 1

    def test_auto_hw_is_1(self):
        assert auto_concurrency(use_hw=True, is_burn=False) == 1

    def test_auto_sw_bounded(self):
        n = auto_concurrency(use_hw=False, is_burn=False)
        assert 1 <= n <= 4

    def test_resolve_manual(self):
        assert resolve_concurrency("4", False, False) == 4

    def test_resolve_auto(self):
        n = resolve_concurrency("auto", False, False)
        assert 1 <= n <= 4

    def test_resolve_clamp(self):
        assert resolve_concurrency("99", False, False) == 8
        assert resolve_concurrency("0", False, False) == 1


class TestClearPending:
    """Soft-stop needs to be able to drop queued tasks without touching
    the one currently running."""

    def test_clear_pending_returns_count(self):
        q = TaskQueue()
        q.enqueue(_make_task("a"))
        q.enqueue(_make_task("b"))
        q.enqueue(_make_task("c"))
        q.dequeue()  # simulate "current" consumed
        assert q.clear_pending() == 2
        assert q.total() == 1
        assert q.pending == []

    def test_clear_pending_empty_queue(self):
        q = TaskQueue()
        assert q.clear_pending() == 0


class TestCancelTokenStateMachine:
    """Per-runnable token invariants."""

    def test_fresh_token_running(self):
        t = CancelToken()
        assert t.state == TokenState.RUNNING
        assert not t.cancelled
        assert not t.paused

    def test_cancel_without_attach_marks_cancelled(self):
        t = CancelToken()
        t.cancel()
        assert t.cancelled
        # No attached proc → straight to CANCELLED (nothing to kill)
        assert t.state == TokenState.CANCELLED

    def test_pause_then_resume_returns_to_running(self):
        t = CancelToken()
        t.pause()
        assert t.state == TokenState.PAUSED
        assert t.paused
        t.resume()
        assert t.state == TokenState.RUNNING
        assert not t.paused

    def test_cancel_unblocks_pause_latch(self):
        t = CancelToken()
        t.pause()
        t.cancel()
        # wait_if_paused must NOT hang after cancel.
        t.wait_if_paused()  # should return immediately

    def test_pause_is_noop_when_cancelled(self):
        t = CancelToken()
        t.cancel()
        t.pause()
        # Once cancelled, pause must not flip us back into PAUSED.
        assert t.state == TokenState.CANCELLED

    def test_detach_after_clean_finish(self):
        t = CancelToken()
        t.detach()
        assert t.state == TokenState.FINISHED


class TestExecutionEventShape:
    """Event bus payload is stable so downstream subscribers stay simple."""

    def test_event_has_default_fields(self):
        e = ExecutionEvent(type=EventType.QUEUED.value, total=5)
        assert e.type == "queued"
        assert e.total == 5
        assert e.progress == 0

    def test_event_types_cover_lifecycle(self):
        assert set(EventType).issuperset({
            EventType.QUEUED, EventType.STARTED,
            EventType.DONE, EventType.ALL_DONE,
            EventType.SOFT_STOP,
        })
