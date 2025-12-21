"""
Async indexing job queue with parallel workers.

Handles background indexing of chat messages without blocking chat responses.
"""
import logging
import queue
import threading
import time
from datetime import datetime
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import os

logger = logging.getLogger(__name__)

# Configuration
INDEX_WORKERS = int(os.getenv("INDEX_WORKERS", "2"))  # Default: 2 workers
BASE_TIMEOUT = 8.0  # Base timeout in seconds
PER_CHUNK_TIMEOUT = 3.5  # Timeout per chunk in seconds
MIN_TIMEOUT = 15.0  # Minimum timeout in seconds
MAX_TIMEOUT = 300.0  # Maximum timeout (5 minutes)
HARD_CAP = 600.0  # Hard cap (10 minutes) - absolute safety limit


class JobState(Enum):
    """Job state enumeration."""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class IndexingJob:
    """Represents an indexing job."""
    job_id: str
    project_id: str
    chat_id: str
    message_id: str
    message_uuid: Optional[str]
    role: str
    content: str
    timestamp: datetime
    message_index: int
    
    # Job metadata
    state: JobState = JobState.QUEUED
    enqueue_time: datetime = field(default_factory=datetime.now)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    estimated_chunks: int = 1
    computed_timeout: float = MIN_TIMEOUT
    error_message: Optional[str] = None
    
    def compute_timeout(self) -> float:
        """Compute dynamic timeout based on estimated chunks."""
        timeout = BASE_TIMEOUT + (PER_CHUNK_TIMEOUT * self.estimated_chunks)
        timeout = max(MIN_TIMEOUT, min(timeout, MAX_TIMEOUT))
        self.computed_timeout = timeout
        return timeout
    
    def get_duration(self) -> Optional[float]:
        """Get job duration in seconds if finished."""
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


class IndexingQueue:
    """Job queue for async indexing with parallel workers."""
    
    def __init__(self, num_workers: int = INDEX_WORKERS):
        self.queue: queue.Queue = queue.Queue()
        self.jobs: Dict[str, IndexingJob] = {}  # job_id -> job
        self.jobs_lock = threading.Lock()
        self.workers: list[threading.Thread] = []
        self.num_workers = num_workers
        self.running = False
        
    def start(self):
        """Start worker threads."""
        if self.running:
            return
        
        self.running = True
        for i in range(self.num_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"IndexWorker-{i+1}",
                daemon=True
            )
            worker.start()
            self.workers.append(worker)
        logger.info(f"[INDEX-QUEUE] Started {self.num_workers} indexing workers")
    
    def stop(self):
        """Stop worker threads (graceful shutdown)."""
        self.running = False
        # Add sentinel values to wake up workers
        for _ in range(self.num_workers):
            self.queue.put(None)
        logger.info(f"[INDEX-QUEUE] Stopping {self.num_workers} indexing workers")
    
    def enqueue(
        self,
        project_id: str,
        chat_id: str,
        message_id: str,
        role: str,
        content: str,
        timestamp: datetime,
        message_index: int,
        message_uuid: Optional[str] = None
    ) -> Tuple[str, bool]:
        """
        Enqueue an indexing job.
        
        Returns:
            Tuple of (job_id, success)
        """
        try:
            # Estimate chunks (rough approximation: ~1000 chars per chunk)
            estimated_chunks = max(1, len(content) // 1000 + 1)
            
            job_id = f"{chat_id}:{message_id}:{int(time.time() * 1000)}"
            job = IndexingJob(
                job_id=job_id,
                project_id=project_id,
                chat_id=chat_id,
                message_id=message_id,
                message_uuid=message_uuid,
                role=role,
                content=content,
                timestamp=timestamp,
                message_index=message_index,
                estimated_chunks=estimated_chunks
            )
            job.compute_timeout()
            
            with self.jobs_lock:
                self.jobs[job_id] = job
            
            self.queue.put(job)
            logger.info(
                f"[INDEX-QUEUE] Enqueued job {job_id} "
                f"(project={project_id}, chunks≈{estimated_chunks}, timeout={job.computed_timeout:.1f}s)"
            )
            return job_id, True
            
        except Exception as e:
            logger.error(f"[INDEX-QUEUE] Failed to enqueue job: {e}", exc_info=True)
            return "", False
    
    def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Get job status for API response."""
        with self.jobs_lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            
            return {
                "job_id": job.job_id,
                "state": job.state.value,
                "enqueue_time": job.enqueue_time.isoformat(),
                "start_time": job.start_time.isoformat() if job.start_time else None,
                "end_time": job.end_time.isoformat() if job.end_time else None,
                "duration": job.get_duration(),
                "estimated_chunks": job.estimated_chunks,
                "computed_timeout": job.computed_timeout,
                "error_message": job.error_message,
                "message_uuid": job.message_uuid
            }
    
    def _worker_loop(self):
        """Worker thread main loop."""
        from memory_service.indexer import index_chat_message
        
        while self.running:
            try:
                job = self.queue.get(timeout=1.0)
                if job is None:  # Sentinel value for shutdown
                    break
                
                self._process_job(job, index_chat_message)
                self.queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[INDEX-QUEUE] Worker error: {e}", exc_info=True)
    
    def _process_job(self, job: IndexingJob, index_func):
        """Process a single indexing job."""
        job.state = JobState.RUNNING
        job.start_time = datetime.now()
        
        logger.info(
            f"[INDEX-QUEUE] Processing job {job.job_id} "
            f"(project={job.project_id}, timeout={job.computed_timeout:.1f}s)"
        )
        
        try:
            # Run indexing with timeout
            start_time = time.time()
            
            # Use threading to enforce timeout
            result = [None, None]  # [success, message_uuid]
            exception = [None]
            
            def run_indexing():
                try:
                    success, message_uuid = index_func(
                        project_id=job.project_id,
                        chat_id=job.chat_id,
                        message_id=job.message_id,
                        role=job.role,
                        content=job.content,
                        timestamp=job.timestamp,
                        message_index=job.message_index
                    )
                    result[0] = success
                    result[1] = message_uuid
                except Exception as e:
                    exception[0] = e
            
            thread = threading.Thread(target=run_indexing, daemon=True)
            thread.start()
            thread.join(timeout=min(job.computed_timeout, HARD_CAP))
            
            elapsed = time.time() - start_time
            
            if thread.is_alive():
                # Job timed out
                job.state = JobState.TIMEOUT
                job.error_message = f"Job exceeded timeout ({job.computed_timeout:.1f}s)"
                logger.warning(
                    f"[INDEX-QUEUE] Job {job.job_id} timed out after {elapsed:.1f}s "
                    f"(limit: {job.computed_timeout:.1f}s)"
                )
            elif exception[0]:
                # Job raised exception
                job.state = JobState.ERROR
                job.error_message = str(exception[0])
                logger.error(
                    f"[INDEX-QUEUE] Job {job.job_id} failed: {exception[0]}",
                    exc_info=exception[0]
                )
            elif result[0]:
                # Job succeeded
                job.state = JobState.SUCCESS
                job.message_uuid = result[1]  # Update with actual message_uuid
                logger.info(
                    f"[INDEX-QUEUE] Job {job.job_id} completed successfully "
                    f"in {elapsed:.1f}s (message_uuid={result[1]})"
                )
            else:
                # Job returned False (partial failure)
                job.state = JobState.ERROR
                job.error_message = "Indexing returned False"
                job.message_uuid = result[1]  # Still capture message_uuid
                logger.warning(
                    f"[INDEX-QUEUE] Job {job.job_id} returned False "
                    f"(message_uuid={result[1]})"
                )
            
            job.end_time = datetime.now()
            
            # Log structured telemetry
            logger.info(
                f"[INDEX-TELEMETRY] job_id={job.job_id} "
                f"chat_id={job.chat_id} message_uuid={job.message_uuid} "
                f"role={job.role} estimated_chunks={job.estimated_chunks} "
                f"computed_timeout={job.computed_timeout:.1f}s hard_cap={HARD_CAP:.1f}s "
                f"start={job.start_time.isoformat()} end={job.end_time.isoformat()} "
                f"duration={job.get_duration():.1f}s status={job.state.value} "
                f"error={job.error_message or 'none'}"
            )
            
        except Exception as e:
            job.state = JobState.ERROR
            job.error_message = str(e)
            job.end_time = datetime.now()
            logger.error(
                f"[INDEX-QUEUE] Job {job.job_id} crashed: {e}",
                exc_info=True
            )
        
        finally:
            # Clean up old jobs (keep last 1000)
            with self.jobs_lock:
                if len(self.jobs) > 1000:
                    # Remove oldest completed jobs
                    sorted_jobs = sorted(
                        self.jobs.items(),
                        key=lambda x: x[1].enqueue_time
                    )
                    for old_job_id, _ in sorted_jobs[:len(self.jobs) - 1000]:
                        if self.jobs[old_job_id].state in (JobState.SUCCESS, JobState.TIMEOUT, JobState.ERROR):
                            del self.jobs[old_job_id]


# Global queue instance
_indexing_queue: Optional[IndexingQueue] = None


def get_indexing_queue() -> IndexingQueue:
    """Get or create the global indexing queue."""
    global _indexing_queue
    if _indexing_queue is None:
        num_workers = INDEX_WORKERS
        _indexing_queue = IndexingQueue(num_workers=num_workers)
        _indexing_queue.start()
    return _indexing_queue

