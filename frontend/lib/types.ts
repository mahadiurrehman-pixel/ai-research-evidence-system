export type VerdictType =
  | "SUPPORTED"
  | "PARTIALLY_SUPPORTED"
  | "NOT_SUPPORTED"
  | "CONTRADICTED"
  | "INCONCLUSIVE";

export type ConfidenceLevel = "HIGH" | "MEDIUM" | "LOW";

export type InvestigationStatus =
  | "CREATED"
  | "ROUTING"
  | "PLANNING"
  | "SEARCHING"
  | "VERIFYING"
  | "COMPLETED"
  | "INCONCLUSIVE"
  | "FAILED";

export type EvidenceSupport =
  | "SUPPORTS"
  | "CONTRADICTS"
  | "NEUTRAL"
  | "IRRELEVANT";

export type SourceType =
  | "PEER_REVIEWED"
  | "PREPRINT"
  | "META_ANALYSIS"
  | "RCT"
  | "GOVERNMENT"
  | "NEWS"
  | "BLOG";

export interface EvidenceCitation {
  source_id: string;
  title: string;
  claim: string;
  reason?: string;
}

export interface EvidenceItem {
  source_id: string;
  title: string;
  authors?: string[];
  year?: number;
  url?: string;
  relevant_passage: string;
  study_design?: string;
  sample_size?: number;
  peer_reviewed?: boolean;
  source_type?: SourceType;
  support_level: EvidenceSupport;
  strength: "HIGH" | "MEDIUM" | "LOW";
  relevance: "HIGH" | "MEDIUM" | "LOW";
  key_claim: string;
  reason: string;
}

export interface VerdictResult {
  verdict: VerdictType;
  confidence: ConfidenceLevel;
  summary: string;
  detailed_reasoning: string;
  supporting_evidence: EvidenceCitation[];
  contradicting_evidence: EvidenceCitation[];
  limitations: string[];
  sub_question_answers?: Record<string, string>;
  recommendations?: string[];
}

export interface Investigation {
  investigation_id: string;
  question: string;
  status: InvestigationStatus;
  verdict?: VerdictResult;
  rounds_used: number;
  evidence_count: number;
  time_taken: string;
  created_at: string;
  route_metadata?: {
    intent: string;
    domain: string;
    complexity: string;
    investigation_level: string;
    reason: string;
  };
  trace_summary: string[];
  raw_evidence_summary?: EvidenceItem[];
}

export interface PipelineStage {
  id: string;
  label: string;
  status: "pending" | "active" | "complete" | "error";
  duration?: number;
  detail?: string;
}