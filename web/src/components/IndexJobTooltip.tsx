import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';

interface IndexJobStatus {
  job_id: string;
  state: 'queued' | 'running' | 'success' | 'timeout' | 'error';
  enqueue_time: string;
  start_time?: string | null;
  end_time?: string | null;
  duration?: number | null;
  estimated_chunks: number;
  computed_timeout: number;
  error_message?: string | null;
  message_uuid?: string | null;
}

interface IndexJobTooltipProps {
  jobId: string | null | undefined;
  indexStatus: 'P' | 'F' | undefined;
  children: React.ReactNode;
}

export const IndexJobTooltip: React.FC<IndexJobTooltipProps> = ({ jobId, indexStatus, children }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [jobStatus, setJobStatus] = useState<IndexJobStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const triggerRef = useRef<HTMLSpanElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ top: 0, left: 0 });

  // Fetch job status when tooltip opens
  useEffect(() => {
    if (isOpen && jobId && !jobStatus && !loading) {
      setLoading(true);
      setError(null);
      axios.get<IndexJobStatus>(`http://127.0.0.1:5858/index-job-status/${jobId}`, { timeout: 2000 })
        .then(response => {
          setJobStatus(response.data);
          setLoading(false);
        })
        .catch(err => {
          if (err.response?.status === 404) {
            setError('Job not found');
          } else {
            setError('Failed to fetch job status');
          }
          setLoading(false);
        });
    }
  }, [isOpen, jobId, jobStatus, loading]);

  // Update tooltip position
  useEffect(() => {
    if (isOpen && triggerRef.current && tooltipRef.current) {
      const triggerRect = triggerRef.current.getBoundingClientRect();
      const tooltipRect = tooltipRef.current.getBoundingClientRect();
      const scrollY = window.scrollY;
      const scrollX = window.scrollX;

      // Position tooltip above the trigger, centered
      setPosition({
        top: triggerRect.top + scrollY - tooltipRect.height - 8,
        left: triggerRect.left + scrollX + (triggerRect.width / 2) - (tooltipRect.width / 2)
      });
    }
  }, [isOpen, jobStatus, loading, error]);

  const formatDuration = (seconds: number | null | undefined): string => {
    if (!seconds) return 'N/A';
    if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  const formatTime = (isoString: string | null | undefined): string => {
    if (!isoString) return 'N/A';
    try {
      const date = new Date(isoString);
      return date.toLocaleTimeString();
    } catch {
      return isoString;
    }
  };

  const getStateColor = (state: string | undefined): string => {
    switch (state) {
      case 'success': return 'text-green-400';
      case 'running': return 'text-blue-400';
      case 'queued': return 'text-yellow-400';
      case 'timeout': return 'text-orange-400';
      case 'error': return 'text-red-400';
      default: return 'text-gray-400';
    }
  };

  // Only show tooltip if we have a job ID or if index status is F (pipeline failure)
  if (!jobId && indexStatus !== 'F') {
    return <>{children}</>;
  }

  return (
    <>
      <span
        ref={triggerRef}
        onMouseEnter={() => setIsOpen(true)}
        onMouseLeave={() => setIsOpen(false)}
        className="cursor-help"
      >
        {children}
      </span>

      {isOpen && typeof document !== 'undefined' && createPortal(
        <div
          ref={tooltipRef}
          className="fixed z-50 bg-slate-800 border border-slate-700 rounded-lg shadow-xl p-3 min-w-[280px] max-w-[400px] text-xs"
          style={{
            top: `${position.top}px`,
            left: `${position.left}px`,
            pointerEvents: 'none'
          }}
        >
          <div className="font-semibold text-slate-200 mb-2">Indexing Job Status</div>
          
          {!jobId && indexStatus === 'F' ? (
            <div className="text-red-400">
              Pipeline failed to accept/queue job
            </div>
          ) : loading ? (
            <div className="text-slate-400">Loading...</div>
          ) : error ? (
            <div className="text-red-400">{error}</div>
          ) : jobStatus ? (
            <div className="space-y-1.5">
              <div className="flex justify-between">
                <span className="text-slate-400">State:</span>
                <span className={getStateColor(jobStatus.state)}>
                  {jobStatus.state.toUpperCase()}
                </span>
              </div>
              
              {jobStatus.message_uuid && (
                <div className="flex justify-between">
                  <span className="text-slate-400">Message UUID:</span>
                  <span className="text-slate-300 font-mono text-[10px] truncate max-w-[180px]" title={jobStatus.message_uuid}>
                    {jobStatus.message_uuid.substring(0, 8)}...
                  </span>
                </div>
              )}
              
              <div className="flex justify-between">
                <span className="text-slate-400">Enqueued:</span>
                <span className="text-slate-300">{formatTime(jobStatus.enqueue_time)}</span>
              </div>
              
              {jobStatus.start_time && (
                <div className="flex justify-between">
                  <span className="text-slate-400">Started:</span>
                  <span className="text-slate-300">{formatTime(jobStatus.start_time)}</span>
                </div>
              )}
              
              {jobStatus.end_time && (
                <div className="flex justify-between">
                  <span className="text-slate-400">Finished:</span>
                  <span className="text-slate-300">{formatTime(jobStatus.end_time)}</span>
                </div>
              )}
              
              {jobStatus.duration !== null && jobStatus.duration !== undefined && (
                <div className="flex justify-between">
                  <span className="text-slate-400">Duration:</span>
                  <span className="text-slate-300">{formatDuration(jobStatus.duration)}</span>
                </div>
              )}
              
              <div className="flex justify-between">
                <span className="text-slate-400">Est. Chunks:</span>
                <span className="text-slate-300">{jobStatus.estimated_chunks}</span>
              </div>
              
              <div className="flex justify-between">
                <span className="text-slate-400">Timeout:</span>
                <span className="text-slate-300">{jobStatus.computed_timeout.toFixed(1)}s</span>
              </div>
              
              {jobStatus.error_message && (
                <div className="mt-2 pt-2 border-t border-slate-700">
                  <div className="text-slate-400 text-[10px] mb-1">Error:</div>
                  <div className="text-red-400 text-[10px] break-words">{jobStatus.error_message}</div>
                </div>
              )}
            </div>
          ) : (
            <div className="text-slate-400">No job status available</div>
          )}
        </div>,
        document.body
      )}
    </>
  );
};

