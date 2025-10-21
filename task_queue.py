"""
task_queue.py - Async Task Queue System
Place this file in your project root directory
"""

import threading
import queue
import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, Callable, List
import traceback


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Task:
    """Represents a single task in the queue"""
    
    def __init__(self, task_id: str, func: Callable, args: tuple, kwargs: dict, user: str = None):
        self.task_id = task_id
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.user = user
        self.status = TaskStatus.PENDING
        self.result = None
        self.error = None
        self.created_at = datetime.now()
        self.started_at = None
        self.completed_at = None
        self.progress = 0  # 0-100
        self.message = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary for JSON serialization"""
        return {
            "task_id": self.task_id,
            "func_name": self.func.__name__,
            "user": self.user,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class TaskQueue:
    """Thread-safe task queue with background workers"""
    
    def __init__(self, max_workers: int = 5):
        self.task_queue = queue.Queue()
        self.tasks: Dict[str, Task] = {}
        self.max_workers = max_workers
        self.workers: List[threading.Thread] = []
        self.lock = threading.Lock()
        self._start_workers()

    def _start_workers(self):
        """Start worker threads"""
        for i in range(self.max_workers):
            worker = threading.Thread(
                target=self._worker, 
                daemon=True, 
                name=f"TaskWorker-{i}"
            )
            worker.start()
            self.workers.append(worker)

    def _worker(self):
        """Worker thread that processes tasks from the queue"""
        while True:
            try:
                task = self.task_queue.get()
                if task is None:  # Poison pill to stop worker
                    break

                # Mark task as running
                with self.lock:
                    task.status = TaskStatus.RUNNING
                    task.started_at = datetime.now()

                try:
                    print(f"[Worker {threading.current_thread().name}] Starting task {task.task_id}: {task.func.__name__}")
                    
                    # Execute the task
                    result = task.func(*task.args, **task.kwargs)
                    
                    # Mark as completed
                    with self.lock:
                        task.status = TaskStatus.COMPLETED
                        task.result = result
                        task.completed_at = datetime.now()
                        task.progress = 100
                        task.message = "Task completed successfully"
                    
                    print(f"[Worker {threading.current_thread().name}] Completed task {task.task_id}")

                except Exception as e:
                    # Mark as failed
                    with self.lock:
                        task.status = TaskStatus.FAILED
                        task.error = str(e)
                        task.completed_at = datetime.now()
                        task.message = f"Task failed: {str(e)}"
                    
                    print(f"[Worker {threading.current_thread().name}] Task {task.task_id} failed: {str(e)}")
                    traceback.print_exc()

                finally:
                    self.task_queue.task_done()

            except Exception as e:
                print(f"[Worker {threading.current_thread().name}] Unexpected error: {e}")
                traceback.print_exc()

    def enqueue(self, func: Callable, *args, user: str = None, **kwargs) -> str:
        """
        Enqueue a new task
        
        Args:
            func: The function to execute
            *args: Positional arguments for the function
            user: Username who initiated the task
            **kwargs: Keyword arguments for the function
            
        Returns:
            task_id: Unique identifier for the task
        """
        task_id = str(uuid.uuid4())
        task = Task(task_id, func, args, kwargs, user)
        
        with self.lock:
            self.tasks[task_id] = task
        
        self.task_queue.put(task)
        print(f"[Queue] Enqueued task {task_id}: {func.__name__} for user {user}")
        
        return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a specific task by ID"""
        with self.lock:
            return self.tasks.get(task_id)

    def get_all_tasks(self, user: str = None) -> List[Dict[str, Any]]:
        """Get all tasks, optionally filtered by user"""
        with self.lock:
            tasks = list(self.tasks.values())
            if user:
                tasks = [t for t in tasks if t.user == user]
            return [t.to_dict() for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)]

    def get_pending_tasks(self, user: str = None) -> List[Dict[str, Any]]:
        """Get all pending tasks"""
        with self.lock:
            tasks = [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]
            if user:
                tasks = [t for t in tasks if t.user == user]
            return [t.to_dict() for t in sorted(tasks, key=lambda x: x.created_at)]

    def get_running_tasks(self, user: str = None) -> List[Dict[str, Any]]:
        """Get all running tasks"""
        with self.lock:
            tasks = [t for t in self.tasks.values() if t.status == TaskStatus.RUNNING]
            if user:
                tasks = [t for t in tasks if t.user == user]
            return [t.to_dict() for t in sorted(tasks, key=lambda x: x.started_at)]

    def get_queue_status(self) -> Dict[str, Any]:
        """Get overall queue status"""
        with self.lock:
            return {
                "queue_size": self.task_queue.qsize(),
                "total_tasks": len(self.tasks),
                "pending": len([t for t in self.tasks.values() if t.status == TaskStatus.PENDING]),
                "running": len([t for t in self.tasks.values() if t.status == TaskStatus.RUNNING]),
                "completed": len([t for t in self.tasks.values() if t.status == TaskStatus.COMPLETED]),
                "failed": len([t for t in self.tasks.values() if t.status == TaskStatus.FAILED]),
                "workers": len(self.workers),
            }

    def clear_completed_tasks(self, older_than_minutes: int = 60) -> int:
        """
        Clear completed/failed tasks older than specified minutes
        
        Args:
            older_than_minutes: Age threshold in minutes
            
        Returns:
            Number of tasks cleared
        """
        cutoff_time = datetime.now().timestamp() - (older_than_minutes * 60)
        with self.lock:
            to_remove = []
            for task_id, task in self.tasks.items():
                if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                    if task.completed_at and task.completed_at.timestamp() < cutoff_time:
                        to_remove.append(task_id)
            
            for task_id in to_remove:
                del self.tasks[task_id]
            
            print(f"[Queue] Cleared {len(to_remove)} old tasks")
            return len(to_remove)

    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a pending task (cannot cancel running tasks)
        
        Args:
            task_id: ID of task to cancel
            
        Returns:
            True if task was cancelled, False otherwise
        """
        with self.lock:
            task = self.tasks.get(task_id)
            if task and task.status == TaskStatus.PENDING:
                task.status = TaskStatus.FAILED
                task.error = "Task cancelled by user"
                task.message = "Task cancelled by user"
                task.completed_at = datetime.now()
                print(f"[Queue] Cancelled task {task_id}")
                return True
            return False

    def shutdown(self):
        """Shutdown all worker threads gracefully"""
        print("[Queue] Shutting down workers...")
        for _ in self.workers:
            self.task_queue.put(None)  # Poison pill
        for worker in self.workers:
            worker.join(timeout=5)
        print("[Queue] All workers stopped")


# Global task queue instance
# Adjust max_workers based on your needs (default: 5)
task_queue = TaskQueue(max_workers=3)


# Cleanup on module unload (optional)
import atexit
atexit.register(task_queue.shutdown)