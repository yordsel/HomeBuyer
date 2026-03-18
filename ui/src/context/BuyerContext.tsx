/**
 * BuyerContext — React context for buyer state in the segment-driven redesign.
 *
 * Separate from PropertyContext (different lifecycle). Populated from:
 * 1. `segment_update` SSE events (classification results)
 * 2. `resume_briefing` SSE events (returning user data)
 * 3. Buyer intake form submissions
 *
 * Persists across property changes — buyer profile is independent of
 * which property the user is looking at.
 *
 * Phase H-2 (#71) of Epic #23.
 */
import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from 'react';
import type {
  SegmentUpdateData,
  ResumeBriefingData,
  BuyerIntakeData,
} from '../types';

// ---------------------------------------------------------------------------
// Context shape
// ---------------------------------------------------------------------------

export interface BuyerContextData {
  /** Detected buyer segment (e.g. "first_time_buyer", "cash_buyer"). */
  segment?: string;
  /** Classification confidence (0–1). */
  segmentConfidence?: number;
  /** Human-readable profile summary from the backend. */
  profileSummary?: string;
  /** Whether the buyer intake form has been completed. */
  intakeCompleted: boolean;
  /** Intake form data (sent with each request while available). */
  intakeData?: BuyerIntakeData;
  /** Resume briefing data for returning users. */
  resumeBriefing?: ResumeBriefingData;
  /** Whether pre-execution is in progress. */
  preExecuting: boolean;
  /** Tools currently being pre-executed. */
  preExecutionTools: string[];
}

interface BuyerContextActions {
  /** Update segment from SSE segment_update event. */
  updateSegment: (data: SegmentUpdateData) => void;
  /** Set resume briefing from SSE resume_briefing event. */
  setResumeBriefing: (data: ResumeBriefingData) => void;
  /** Record buyer intake form submission. */
  completeIntake: (data: BuyerIntakeData) => void;
  /** Clear intake (e.g. on new conversation). */
  clearIntake: () => void;
  /** Set pre-execution status. */
  setPreExecuting: (tools: string[]) => void;
  /** Clear pre-execution status. */
  clearPreExecuting: () => void;
  /** Dismiss the resume briefing card. */
  dismissBriefing: () => void;
  /** Reset all buyer state (e.g. on logout). */
  resetBuyer: () => void;
}

type BuyerContextType = BuyerContextData & BuyerContextActions;

const BuyerContext = createContext<BuyerContextType | null>(null);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function BuyerProvider({ children }: { children: ReactNode }) {
  const [segment, setSegment] = useState<string | undefined>();
  const [segmentConfidence, setSegmentConfidence] = useState<number | undefined>();
  const [profileSummary, setProfileSummary] = useState<string | undefined>();
  const [intakeCompleted, setIntakeCompleted] = useState(false);
  const [intakeData, setIntakeData] = useState<BuyerIntakeData | undefined>();
  const [resumeBriefing, setResumeBriefingState] = useState<ResumeBriefingData | undefined>();
  const [preExecuting, setPreExecutingState] = useState(false);
  const [preExecutionTools, setPreExecutionTools] = useState<string[]>([]);

  const updateSegment = useCallback((data: SegmentUpdateData) => {
    setSegment(data.segment);
    setSegmentConfidence(data.confidence);
    setProfileSummary(data.profile_summary || undefined);
  }, []);

  const setResumeBriefing = useCallback((data: ResumeBriefingData) => {
    setResumeBriefingState(data);
  }, []);

  const completeIntake = useCallback((data: BuyerIntakeData) => {
    setIntakeData(data);
    setIntakeCompleted(true);
  }, []);

  const clearIntake = useCallback(() => {
    setIntakeData(undefined);
    setIntakeCompleted(false);
  }, []);

  const setPreExecuting = useCallback((tools: string[]) => {
    setPreExecutingState(true);
    setPreExecutionTools(tools);
  }, []);

  const clearPreExecuting = useCallback(() => {
    setPreExecutingState(false);
    setPreExecutionTools([]);
  }, []);

  const dismissBriefing = useCallback(() => {
    setResumeBriefingState(undefined);
  }, []);

  const resetBuyer = useCallback(() => {
    setSegment(undefined);
    setSegmentConfidence(undefined);
    setProfileSummary(undefined);
    setIntakeCompleted(false);
    setIntakeData(undefined);
    setResumeBriefingState(undefined);
    setPreExecutingState(false);
    setPreExecutionTools([]);
  }, []);

  const value: BuyerContextType = {
    segment,
    segmentConfidence,
    profileSummary,
    intakeCompleted,
    intakeData,
    resumeBriefing,
    preExecuting,
    preExecutionTools,
    updateSegment,
    setResumeBriefing,
    completeIntake,
    clearIntake,
    setPreExecuting,
    clearPreExecuting,
    dismissBriefing,
    resetBuyer,
  };

  return (
    <BuyerContext.Provider value={value}>
      {children}
    </BuyerContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useBuyerContext(): BuyerContextType {
  const ctx = useContext(BuyerContext);
  if (!ctx) {
    throw new Error('useBuyerContext must be used within a BuyerProvider');
  }
  return ctx;
}
